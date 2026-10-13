"""Docker runtime engine for student development containers and evaluators."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import stat
import tarfile
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional

import docker
from docker.errors import NotFound
from docker.models.containers import Container
from requests.exceptions import Timeout

from shared.contracts import (
    EvaluatorOutput,
    ManagerGradeResponse,
    RuntimeState,
)

logger = logging.getLogger(__name__)

# Strict container resource quotas
CONTAINER_CPU_LIMIT = int(0.5 * 1e9)  # 0.5 CPU
CONTAINER_MEM_LIMIT = "512m"          # 512MB RAM
CONTAINER_PIDS_LIMIT = 96             # 96 processes


def _remove_container(container: Container, timeout: int) -> None:
    try:
        container.stop(timeout=timeout)
    except NotFound:
        return
    except Exception as exc:
        logger.warning("Could not stop container %s; forcing removal: %s", container.name, exc)
    try:
        container.remove(force=True)
    except NotFound:
        pass


def _validate_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ValueError("Invalid student or operation identifier")
    return value


def _validate_workspace(workspace_dir: str) -> Path:
    path = Path(workspace_dir)
    if not workspace_dir or path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0].startswith("."):
        raise ValueError("Workspace must be a relative directory inside the student volume")
    return path


def _open_directory(path: Path) -> int:
    """Open a directory without following a student-controlled symlink."""
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def _write_file(directory_fd: int, name: str, contents: bytes, mode: int, uid: int) -> None:
    """Replace a file atomically, including an existing symlink or hard link."""
    temp_name = f".{name}-{os.urandom(8).hex()}"
    fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=directory_fd)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            os.fchown(stream.fileno(), uid, uid)
            stream.write(contents)
        os.replace(temp_name, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
    finally:
        try:
            os.unlink(temp_name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def _read_evaluator_output(path: Path) -> EvaluatorOutput:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "r", encoding="utf-8") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
            raise ValueError("Evaluator output must be a regular JSON file smaller than 1 MB")
        return EvaluatorOutput.model_validate(json.load(stream))


class ConflictError(Exception):
    def __init__(self, message: str, code: str = "OPERATION_IN_PROGRESS"):
        super().__init__(message)
        self.code = code


class DockerRuntime:
    def __init__(
        self,
        docker_client: docker.DockerClient,
        platform_instance: str,
        ssh_host: str,
        ssh_bind_address: str = "0.0.0.0",
        ssh_port_min: int = 22000,
        ssh_port_max: int = 22999,
        snapshots_path: Optional[str | Path] = None,
    ):
        self.client = docker_client
        self.platform_instance = platform_instance
        self.ssh_host = ssh_host
        self.ssh_bind_address = ssh_bind_address
        self.ssh_port_min = ssh_port_min
        self.ssh_port_max = ssh_port_max
        self.snapshots_path = Path(snapshots_path or os.environ.get("SNAPSHOTS_PATH", "/data/snapshots"))

        # Locks
        self._locks_dict_lock = threading.Lock()
        self._student_locks: Dict[str, threading.Lock] = {}
        self._port_lock = threading.Lock()
        self._allocated_ports: Dict[int, str] = {}  # port -> student_id

        # Memory operation tracker per student
        self._operations_lock = threading.Lock()
        self._student_operations: Dict[str, Dict[str, Any]] = {}

    def get_student_lock(self, student_id: str) -> threading.Lock:
        _validate_identifier(student_id)
        with self._locks_dict_lock:
            if student_id not in self._student_locks:
                self._student_locks[student_id] = threading.Lock()
            return self._student_locks[student_id]

    def cleanup_on_startup(self) -> None:
        """Removes existing containers belonging to this platform instance before builds."""
        logger.info("Cleaning up lingering containers on startup...")
        containers = self.client.containers.list(
            all=True,
            filters={
                "label": [
                    "platform.app=devops-eval",
                    f"platform.instance={self.platform_instance}",
                ]
            },
        )
        for container in containers:
            logger.info("Removing lingering container %s (%s)", container.name, container.id[:12])
            _remove_container(container, timeout=2)

    def allocate_port(self, student_id: str) -> int:
        with self._port_lock:
            # Query all host ports currently in use by Docker containers
            used_host_ports = set(self._allocated_ports)
            # Other students may remove evaluators between listing and inspection.
            for container in self.client.containers.list(all=True, ignore_removed=True):
                ports_dict = container.attrs.get("NetworkSettings", {}).get("Ports", {}) or {}
                for bindings in ports_dict.values():
                    for binding in bindings or []:
                        if binding.get("HostPort"):
                            used_host_ports.add(int(binding["HostPort"]))

            for port in range(self.ssh_port_min, self.ssh_port_max + 1):
                if port in used_host_ports:
                    continue

                self._allocated_ports[port] = student_id
                return port

            raise RuntimeError("SSH_PORTS_EXHAUSTED: No available SSH ports in configured range")

    def release_port_for_student(self, student_id: str) -> None:
        with self._port_lock:
            to_remove = [p for p, s_id in self._allocated_ports.items() if s_id == student_id]
            for p in to_remove:
                del self._allocated_ports[p]

    def get_student_volume_name(self, student_id: str) -> str:
        _validate_identifier(student_id)
        return f"devops-{self.platform_instance}-student-{student_id}"

    def ensure_student_volume(self, student_id: str):
        vol_name = self.get_student_volume_name(student_id)
        try:
            return self.client.volumes.get(vol_name)
        except NotFound:
            return self.client.volumes.create(
                name=vol_name,
                labels={
                    "platform.app": "devops-eval",
                    "platform.instance": self.platform_instance,
                    "platform.student_id": student_id,
                    "platform.kind": "workspace",
                },
            )

    def update_student_volume_key(self, student_id: str, ssh_public_key: str) -> None:
        """Update SSH access without following paths controlled by the student."""
        lock = self.get_student_lock(student_id)
        if not lock.acquire(blocking=False):
            raise ConflictError("Une opération est déjà en cours pour cet étudiant")
        try:
            self._write_student_volume_key(student_id, ssh_public_key)
        finally:
            lock.release()

    def _write_student_volume_key(self, student_id: str, ssh_public_key: str) -> None:
        vol_path = self.get_student_volume_path(student_id)
        if vol_path is None:
            raise RuntimeError("Student volume mountpoint is not accessible")
        volume_fd = _open_directory(vol_path)
        ssh_fd = None
        try:
            try:
                os.mkdir(".ssh", mode=0o700, dir_fd=volume_fd)
            except FileExistsError:
                pass
            ssh_fd = os.open(".ssh", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=volume_fd)
            os.fchmod(ssh_fd, 0o700)
            os.fchown(ssh_fd, 1000, 1000)
            # An empty key intentionally clears old access after key removal.
            key = ssh_public_key.strip()
            _write_file(ssh_fd, "authorized_keys", ((key + "\n") if key else "").encode("utf-8"), 0o600, 1000)
            try:
                os.stat(".vimrc", dir_fd=volume_fd, follow_symlinks=False)
            except FileNotFoundError:
                _write_file(volume_fd, ".vimrc", b"set number\nset tabstop=4\nset shiftwidth=4\nset expandtab\nsyntax on\n", 0o644, 1000)
            os.fchown(volume_fd, 1000, 1000)
        finally:
            if ssh_fd is not None:
                os.close(ssh_fd)
            os.close(volume_fd)

    def get_student_volume_path(self, student_id: str) -> Optional[Path]:
        vol = self.ensure_student_volume(student_id)
        mountpoint = vol.attrs.get("Mountpoint")
        if not mountpoint:
            vol.reload()
            mountpoint = vol.attrs.get("Mountpoint")
        return Path(mountpoint) if mountpoint else None

    def create_exercise_snapshot(self, student_id: str, workspace_dir: str, operation_id: str) -> Path:
        """Archive student work in persistent storage outside the student-owned volume."""
        _validate_identifier(student_id)
        _validate_identifier(operation_id)
        workspace = _validate_workspace(workspace_dir)
        vol_path = self.get_student_volume_path(student_id)
        if vol_path is None:
            raise RuntimeError("Student volume mountpoint is not accessible")

        exercise_dir = vol_path / workspace
        if not exercise_dir.resolve().is_relative_to(vol_path.resolve()):
            raise ValueError("Exercise workspace resolves outside the student volume")

        self.snapshots_path.mkdir(mode=0o700, parents=True, exist_ok=True)
        root_fd = _open_directory(self.snapshots_path)
        try:
            os.fchmod(root_fd, 0o700)
            os.fchown(root_fd, 0, 0)
            try:
                os.mkdir(student_id, mode=0o700, dir_fd=root_fd)
            except FileExistsError:
                pass
            directory_fd = os.open(student_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        finally:
            os.close(root_fd)
        snapshots_dir = self.snapshots_path / student_id
        temp_name = f".{operation_id}-{os.urandom(8).hex()}.tar.gz"
        try:
            os.fchmod(directory_fd, 0o700)
            os.fchown(directory_fd, 0, 0)
            fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
            with os.fdopen(fd, "wb") as stream:
                with tarfile.open(fileobj=stream, mode="w:gz", dereference=False) as archive:
                    if exercise_dir.exists() or exercise_dir.is_symlink():
                        archive.add(exercise_dir, arcname=str(workspace))
            os.replace(temp_name, f"{operation_id}.tar.gz", src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            return snapshots_dir / f"{operation_id}.tar.gz"
        finally:
            try:
                os.unlink(temp_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            os.close(directory_fd)

    def open_student_snapshot(self, student_id: str, operation_id: str) -> Optional[BinaryIO]:
        """Hold an archive descriptor so later path replacement cannot redirect a read."""
        _validate_identifier(student_id)
        _validate_identifier(operation_id)
        try:
            directory_fd = _open_directory(self.snapshots_path / student_id)
        except FileNotFoundError:
            return None
        try:
            directory_info = os.fstat(directory_fd)
            if directory_info.st_uid != os.geteuid() or directory_info.st_mode & 0o077:
                raise ValueError("Snapshot directory must be private and owned by the manager")
            try:
                fd = os.open(f"{operation_id}.tar.gz", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
            except FileNotFoundError:
                return None
            file_info = os.fstat(fd)
            if not stat.S_ISREG(file_info.st_mode) or file_info.st_uid != os.geteuid() or file_info.st_mode & 0o077:
                os.close(fd)
                raise ValueError("Snapshot must be a private regular file owned by the manager")
            return os.fdopen(fd, "rb")
        finally:
            os.close(directory_fd)

    def get_dev_container_name(self, student_id: str) -> str:
        _validate_identifier(student_id)
        return f"devops-{self.platform_instance}-dev-{student_id}"

    def find_student_dev_container(self, student_id: str) -> Optional[Container]:
        try:
            c = self.client.containers.get(self.get_dev_container_name(student_id))
            if c.status in ("running", "restarting"):
                return c
            return None
        except NotFound:
            return None

    def find_all_student_containers(self, student_id: str) -> List[Container]:
        _validate_identifier(student_id)
        return self.client.containers.list(
            all=True,
            filters={
                "label": [
                    "platform.app=devops-eval",
                    f"platform.instance={self.platform_instance}",
                    f"platform.student_id={student_id}",
                ]
            },
        )

    def get_operation_info(self, student_id: str, operation_id: str) -> Optional[Dict[str, Any]]:
        _validate_identifier(student_id)
        _validate_identifier(operation_id)
        with self._operations_lock:
            operation = self._student_operations.get(student_id)
            if operation and operation["operation_id"] == operation_id:
                return dict(operation)
        return None

    def get_environment_info(self, student_id: str) -> Dict[str, Any]:
        """Returns real environment state from Docker and active operations."""
        with self._operations_lock:
            operation = self._student_operations.get(student_id)
            op_data = dict(operation) if operation else None

        container = self.find_student_dev_container(student_id)
        if container:
            ports = container.attrs.get("NetworkSettings", {}).get("Ports", {}) or {}
            port_bindings = ports.get("22/tcp")
            host_port = None
            if port_bindings:
                host_port = int(port_bindings[0].get("HostPort", 0))

            labels = container.labels or {}
            ex_id = labels.get("platform.exercise_id")

            return {
                "state": RuntimeState.RUNNING.value if container.status == "running" else RuntimeState.STARTING.value,
                "exercise_id": ex_id,
                "ssh": {
                    "host": self.ssh_host,
                    "port": host_port,
                    "user": "student",
                } if host_port else None,
                "active_operation": op_data,
            }

        return {
            "state": RuntimeState.STOPPED.value,
            "exercise_id": None,
            "ssh": None,
            "active_operation": op_data,
        }

    def start_dev_environment(
        self,
        student_id: str,
        operation_id: str,
        exercise_id: str,
        exercise_name: str,
        image_id: str,
        workspace_dir: str,
        ssh_public_key: str,
    ) -> Dict[str, Any]:
        _validate_identifier(operation_id)
        _validate_workspace(workspace_dir)
        if not ssh_public_key.strip():
            raise ValueError("An SSH public key is required to start the environment")
        lock = self.get_student_lock(student_id)
        if not lock.acquire(blocking=False):
            raise ConflictError("Une opération est déjà en cours pour cet étudiant", "OPERATION_IN_PROGRESS")

        port = None
        container = None
        operation_started = False
        try:
            with self._operations_lock:
                existing_op = self._student_operations.get(student_id)
                if existing_op and existing_op.get("operation_id") == operation_id:
                    if existing_op.get("type") != "start" or existing_op.get("exercise_id") != exercise_id:
                        raise ConflictError("L'identifiant d'opération est déjà utilisé", "OPERATION_CONFLICT")
                    if existing_op.get("status") == "completed":
                        return existing_op.get("result", {})
                    if existing_op.get("status") == "running":
                        raise ConflictError("Cette opération est déjà en cours", "OPERATION_IN_PROGRESS")

                self._student_operations[student_id] = {
                    "operation_id": operation_id,
                    "type": "start",
                    "status": "running",
                    "started_at": time.time(),
                    "exercise_id": exercise_id,
                    "result": None,
                }
                operation_started = True

            existing = self.find_student_dev_container(student_id)
            if existing:
                raise ConflictError("Un environnement de développement est déjà actif", "ENVIRONMENT_ALREADY_RUNNING")

            # 1. Ensure student volume exists
            vol = self.ensure_student_volume(student_id)
            self._write_student_volume_key(student_id, ssh_public_key)

            port = self.allocate_port(student_id)
            c_name = self.get_dev_container_name(student_id)

            try:
                old = self.client.containers.get(c_name)
                old.remove(force=True)
            except NotFound:
                pass

            # 2. Create container with volume mounted to /home/student
            container = self.client.containers.create(
                image=image_id,
                name=c_name,
                labels={
                    "platform.app": "devops-eval",
                    "platform.instance": self.platform_instance,
                    "platform.student_id": student_id,
                    "platform.kind": "dev",
                    "platform.exercise_id": exercise_id,
                    "platform.operation_id": operation_id,
                },
                ports={"22/tcp": (self.ssh_bind_address, port)},
                volumes={vol.name: {"bind": "/home/student", "mode": "rw"}},
                environment={"WORKSPACE_DIR": f"/home/student/{workspace_dir}"},
                nano_cpus=CONTAINER_CPU_LIMIT,
                mem_limit=CONTAINER_MEM_LIMIT,
                pids_limit=CONTAINER_PIDS_LIMIT,
                restart_policy={"Name": "no"},
            )

            # 3. Start container
            container.start()

            result = {
                "state": RuntimeState.RUNNING.value,
                "exercise": {"id": exercise_id, "name": exercise_name},
                "ssh": {
                    "host": self.ssh_host,
                    "port": port,
                    "user": "student",
                },
            }

            with self._operations_lock:
                self._student_operations[student_id]["status"] = "completed"
                self._student_operations[student_id]["result"] = result

            return result

        except Exception as exc:
            if container is not None:
                try:
                    _remove_container(container, timeout=2)
                except Exception:
                    logger.exception("Failed to remove development container after a failed start")
            if port is not None:
                self.release_port_for_student(student_id)
            with self._operations_lock:
                operation = self._student_operations.get(student_id)
                if operation_started and operation:
                    self._student_operations[student_id]["status"] = "failed"
                    self._student_operations[student_id]["error_message"] = str(exc)
            raise
        finally:
            lock.release()

    def stop_student_environment(self, student_id: str, operation_id: str) -> Dict[str, Any]:
        _validate_identifier(operation_id)
        lock = self.get_student_lock(student_id)
        if not lock.acquire(blocking=False):
            raise ConflictError("Une opération est déjà en cours pour cet étudiant", "OPERATION_IN_PROGRESS")

        try:
            with self._operations_lock:
                existing_op = self._student_operations.get(student_id)
                if existing_op and existing_op.get("operation_id") == operation_id:
                    if existing_op["type"] != "stop":
                        raise ConflictError("L'identifiant d'opération est déjà utilisé", "OPERATION_CONFLICT")
                    if existing_op["status"] == "completed":
                        return existing_op["result"]
                self._student_operations[student_id] = {
                    "operation_id": operation_id,
                    "type": "stop",
                    "status": "running",
                    "started_at": time.time(),
                    "result": None,
                }

            containers = self.find_all_student_containers(student_id)
            for c in containers:
                _remove_container(c, timeout=5)

            still_alive = self.find_all_student_containers(student_id)
            if still_alive:
                logger.error(f"Containers still remain for student {student_id}: {[c.name for c in still_alive]}")
                raise RuntimeError("Failed to completely stop and remove all containers for student")

            self.release_port_for_student(student_id)

            result = {"state": RuntimeState.STOPPED.value}
            with self._operations_lock:
                self._student_operations[student_id]["status"] = "completed"
                self._student_operations[student_id]["result"] = result

            return result

        except Exception as exc:
            with self._operations_lock:
                operation = self._student_operations.get(student_id)
                if operation and operation["operation_id"] == operation_id and operation["type"] == "stop":
                    self._student_operations[student_id]["status"] = "failed"
                    self._student_operations[student_id]["error_message"] = str(exc)
            raise
        finally:
            lock.release()

    def grade_student_exercise(
        self,
        student_id: str,
        operation_id: str,
        exercise_id: str,
        evaluator_image_id: str,
        workspace_dir: str,
        timeout_seconds: int = 120,
    ) -> ManagerGradeResponse:
        """Stop the workspace, snapshot it, then run and remove a bounded evaluator."""
        _validate_identifier(operation_id)
        _validate_workspace(workspace_dir)
        if not 1 <= timeout_seconds <= 300:
            raise ValueError("Evaluation timeout must be between 1 and 300 seconds")
        lock = self.get_student_lock(student_id)
        if not lock.acquire(blocking=False):
            raise ConflictError("Une opération est déjà en cours pour cet étudiant", "OPERATION_IN_PROGRESS")

        eval_container = None
        temp_dir = None
        operation_started = False
        try:
            with self._operations_lock:
                existing_op = self._student_operations.get(student_id)
                if existing_op and existing_op.get("operation_id") == operation_id:
                    if existing_op.get("type") != "grade" or existing_op.get("exercise_id") != exercise_id:
                        raise ConflictError("L'identifiant d'opération est déjà utilisé", "OPERATION_CONFLICT")
                    if existing_op.get("status") == "completed":
                        return existing_op.get("result")
                    if existing_op.get("status") == "running":
                        raise ConflictError("Cette évaluation est déjà en cours", "OPERATION_IN_PROGRESS")

                self._student_operations[student_id] = {
                    "operation_id": operation_id,
                    "type": "grade",
                    "status": "running",
                    "started_at": time.time(),
                    "exercise_id": exercise_id,
                    "result": None,
                }
                operation_started = True

            try:
                for container in self.find_all_student_containers(student_id):
                    _remove_container(container, timeout=5)
                if self.find_all_student_containers(student_id):
                    raise RuntimeError("Student containers remain; evaluation cannot start")
                self.release_port_for_student(student_id)

                vol = self.ensure_student_volume(student_id)
                self.create_exercise_snapshot(student_id, workspace_dir, operation_id)
                temp_dir = tempfile.mkdtemp(prefix=f"evalops-grade-{operation_id}-", dir="/tmp")
                os.chmod(temp_dir, 0o777)

                eval_name = f"devops-{self.platform_instance}-eval-{student_id}-{operation_id}"
                try:
                    old = self.client.containers.get(eval_name)
                    old.remove(force=True)
                except NotFound:
                    pass

                eval_container = self.client.containers.create(
                    image=evaluator_image_id,
                    name=eval_name,
                    labels={
                        "platform.app": "devops-eval",
                        "platform.instance": self.platform_instance,
                        "platform.student_id": student_id,
                        "platform.kind": "evaluator",
                        "platform.exercise_id": exercise_id,
                        "platform.operation_id": operation_id,
                    },
                    volumes={
                        vol.name: {"bind": "/home/student", "mode": "ro"},
                        temp_dir: {"bind": "/result", "mode": "rw"},
                    },
                    environment={"WORKSPACE_DIR": f"/home/student/{workspace_dir}"},
                    network_mode="none",
                    nano_cpus=CONTAINER_CPU_LIMIT,
                    mem_limit=CONTAINER_MEM_LIMIT,
                    pids_limit=CONTAINER_PIDS_LIMIT,
                    restart_policy={"Name": "no"},
                )
                eval_container.start()

                timed_out = False
                exit_code = None
                try:
                    exit_code = eval_container.wait(timeout=timeout_seconds).get("StatusCode", -1)
                except Timeout:
                    timed_out = True
                    try:
                        eval_container.kill()
                    except NotFound:
                        pass

                stdout = ""
                stderr = ""
                try:
                    stdout = eval_container.logs(stdout=True, stderr=False, tail=1000).decode("utf-8", errors="replace")[-65536:]
                    stderr = eval_container.logs(stdout=False, stderr=True, tail=1000).decode("utf-8", errors="replace")[-65536:]
                except Exception:
                    logger.warning("Could not collect evaluator logs", exc_info=True)

                response_args = {
                    "operation_id": operation_id,
                    "exercise_id": exercise_id,
                    "stdout": stdout,
                    "stderr": stderr,
                }
                if timed_out:
                    response = ManagerGradeResponse(
                        **response_args,
                        status="error",
                        error_code="EVALUATION_TIMEOUT",
                        error_message=f"Le délai d'évaluation de {timeout_seconds}s a été dépassé",
                    )
                elif exit_code != 0:
                    response = ManagerGradeResponse(
                        **response_args,
                        status="error",
                        error_code="EVALUATOR_FAILED",
                        error_message=f"L'évaluateur s'est terminé avec le code d'erreur {exit_code}",
                    )
                else:
                    try:
                        eval_out = _read_evaluator_output(Path(temp_dir) / "result.json")
                        response = ManagerGradeResponse(
                            **response_args,
                            status="completed",
                            tests=eval_out.tests,
                        )
                    except (OSError, ValueError, TypeError) as exc:
                        response = ManagerGradeResponse(
                            **response_args,
                            status="error",
                            error_code="INVALID_EVALUATION_RESULT",
                            error_message=f"Structure du résultat invalide: {exc}",
                        )

            finally:
                # Do not report completion if the evaluator could not be removed.
                try:
                    if eval_container is not None:
                        _remove_container(eval_container, timeout=2)
                finally:
                    if temp_dir is not None:
                        shutil.rmtree(temp_dir)

            with self._operations_lock:
                self._student_operations[student_id]["status"] = "completed"
                self._student_operations[student_id]["result"] = response

            return response
        except Exception as exc:
            if operation_started:
                with self._operations_lock:
                    self._student_operations[student_id]["status"] = "failed"
                    self._student_operations[student_id]["error_message"] = str(exc)
            raise
        finally:
            lock.release()
