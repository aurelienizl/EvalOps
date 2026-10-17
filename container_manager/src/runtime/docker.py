"""Docker primitives for development, grading and recovery actions.

All blocking SDK calls will run in bounded threads. No database state changes
belong here; callers decide when confirmed Docker outcomes may be persisted.
"""

from __future__ import annotations

import asyncio
import functools
import io
import tarfile
import time
import docker
from docker.errors import NotFound, ImageNotFound, APIError
from docker.types import LogConfig, Ulimit


from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID


@dataclass(frozen=True)
class ManagedContainer:
    id: str
    user_id: UUID
    exercise_id: str
    operation_id: UUID
    kind: Literal["development", "evaluator"]
    running: bool
    ssh_port: int | None = None


@dataclass(frozen=True)
class ContainerExit:
    exit_code: int | None
    timed_out: bool = False
    oom_killed: bool = False


async def io_call(function, *args, **kwargs):
    """Cancellation waits for the bounded SDK call, avoiding late orphan creation."""
    task = asyncio.create_task(asyncio.to_thread(functools.partial(function, *args, **kwargs)))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        finally:
            raise


def open_docker_client(settings):
    client = docker.from_env(timeout=30)
    client.ping()
    return client


def close_docker_client(client):
    client.close()


async def build_image(client, context, tag):
    def build():
        try:
            return client.images.get(tag).id
        except ImageNotFound:
            image, _ = client.images.build(path=str(context), tag=tag, rm=True, forcerm=True)
            return image.id

    return await io_call(build)


def _labels(settings, user_id, exercise_id, operation_id, kind):
    return {
        "evalops.deployment": settings.deployment_id,
        "evalops.user": str(user_id),
        "evalops.exercise": exercise_id,
        "evalops.operation": str(operation_id),
        "evalops.kind": kind,
    }


def _model(container):
    from uuid import UUID

    labels = container.labels
    ports = container.attrs["NetworkSettings"].get("Ports", {}).get("22/tcp")
    return ManagedContainer(
        container.id,
        UUID(labels["evalops.user"]),
        labels["evalops.exercise"],
        UUID(labels["evalops.operation"]),
        labels["evalops.kind"],
        container.status == "running",
        int(ports[0]["HostPort"]) if ports else None,
    )


def _limits(settings):
    return dict(
        mem_limit=settings.container_memory_bytes,
        memswap_limit=settings.container_memory_bytes,
        nano_cpus=int(settings.container_cpus * 1e9),
        pids_limit=settings.container_pids_limit,
        log_config=LogConfig(type="json-file", config={"max-size": "1m", "max-file": "1"}),
        security_opt=["no-new-privileges:true"],
        ulimits=[Ulimit(name="nofile", soft=256, hard=256)],
    )


async def create_development_container(
    client,
    settings,
    user_id,
    exercise_id,
    operation_id,
    image,
    workspace,
    workspace_dir,
    authorized_key,
):
    name = f"evalops-{settings.deployment_id}-dev-{operation_id}"
    labels = _labels(settings, user_id, exercise_id, operation_id, "development")

    def create():
        try:
            container = client.containers.get(name)
        except NotFound:
            netname = name + "-net"
            try:
                network = client.networks.get(netname)
            except NotFound:
                network = client.networks.create(netname, driver="bridge", labels=labels)
            for port in range(settings.ssh_port_min, settings.ssh_port_max + 1):
                container = None
                try:
                    keys = authorized_key.parent
                    container = client.containers.create(
                        image,
                        name=name,
                        labels=labels,
                        entrypoint=[
                            "/bin/sh",
                            "-c",
                            "mkdir -p /run/sshd && exec /usr/sbin/sshd -D -e -f /etc/ssh/sshd_config",
                        ],
                        environment={"WORKSPACE_DIR": f"/home/student/{workspace_dir}"},
                        volumes={
                            str(workspace): {
                                "bind": f"/home/student/{workspace_dir}",
                                "mode": "rw",
                            },
                            str(authorized_key): {
                                "bind": "/etc/training/authorized_keys/student",
                                "mode": "ro",
                            },
                            str(keys / "sshd_config"): {
                                "bind": "/etc/ssh/sshd_config",
                                "mode": "ro",
                            },
                            str(keys / "host_key"): {
                                "bind": "/etc/training/host_key",
                                "mode": "ro",
                            },
                        },
                        read_only=True,
                        tmpfs={
                            "/tmp": "rw,exec,nosuid,nodev,size=134217728,mode=1777",
                            "/run": "rw,nosuid,nodev,size=8388608,mode=755",
                        },
                        network=network.name,
                        ports={"22/tcp": (settings.ssh_bind_address, port)},
                        cap_drop=["ALL"],
                        cap_add=[
                            "CHOWN",
                            "DAC_OVERRIDE",
                            "FOWNER",
                            "SETUID",
                            "SETGID",
                            "SYS_CHROOT",
                            "KILL",
                            "NET_BIND_SERVICE",
                            "AUDIT_WRITE",
                        ],
                        **_limits(settings),
                    )
                    container.start()
                    break
                except APIError as exc:
                    if container:
                        container.remove(force=True)
                    if (
                        "port is already allocated" not in str(exc).lower()
                        and "address already in use" not in str(exc).lower()
                    ):
                        raise
            else:
                raise RuntimeError("SSH port range exhausted")
        container.reload()
        if container.status != "running":
            container.start()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            container.reload()
            if container.status != "running":
                raise RuntimeError("Development container exited before SSH readiness")
            health = container.attrs["State"].get("Health", {}).get("Status")
            if health == "healthy":
                model = _model(container)
                if not model.ssh_port:
                    raise RuntimeError("Docker did not publish an SSH port")
                return model
            if health is None:
                check = container.exec_run(["/bin/sh", "-c", "test -s /run/sshd.pid"])
                if check.exit_code == 0:
                    return _model(container)
            time.sleep(1)
        raise TimeoutError("SSH readiness timeout")

    return await io_call(create)


async def stop_and_remove_container(client, container_id, grace_seconds):
    def remove():
        try:
            container = client.containers.get(container_id)
        except NotFound:
            return
        labels = container.labels
        networks = list(container.attrs["NetworkSettings"]["Networks"])
        if container.status == "running":
            try:
                container.stop(timeout=grace_seconds)
            except APIError:
                container.kill()
        container.remove(force=True)
        try:
            client.containers.get(container_id)
        except NotFound:
            for name in networks:
                try:
                    network = client.networks.get(name)
                    if network.attrs.get("Labels", {}).get("evalops.deployment") == labels.get(
                        "evalops.deployment"
                    ):
                        network.remove()
                except (NotFound, APIError):
                    pass
            return
        raise RuntimeError("Container removal was not confirmed")

    await io_call(remove)


async def create_evaluator_container(
    client, settings, user_id, exercise_id, evaluation_id, image, workspace, workspace_dir
):
    def create():
        name = f"evalops-{settings.deployment_id}-eval-{evaluation_id}"
        try:
            return _model(client.containers.get(name))
        except NotFound:
            pass
        container = client.containers.create(
            image,
            name=name,
            labels=_labels(settings, user_id, exercise_id, evaluation_id, "evaluator"),
            entrypoint=["python3", "-I", "/runner.py"],
            working_dir="/app",
            environment={
                "WORKSPACE_DIR": f"/home/student/{workspace_dir}",
                "RESULT_DIR": "/result",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            volumes={str(workspace): {"bind": f"/home/student/{workspace_dir}", "mode": "ro"}},
            read_only=True,
            network_mode="none",
            user="0:0",
            cap_drop=["ALL"],
            cap_add=["CHOWN", "DAC_OVERRIDE", "FOWNER", "SETUID", "SETGID", "KILL"],
            tmpfs={
                "/tmp": "rw,exec,nosuid,nodev,size=134217728,mode=1777",
                "/result": "rw,nosuid,nodev,noexec,size=2097152,mode=0700",
            },
            **_limits(settings),
        )
        try:
            container.start()
            return _model(container)
        except BaseException:
            container.remove(force=True)
            raise

    return await io_call(create)


async def wait_for_evaluator(client, container_id, timeout_seconds):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        container = await io_call(client.containers.get, container_id)
        state = container.attrs["State"]
        if not state["Running"]:
            return ContainerExit(state.get("ExitCode"), oom_killed=state.get("OOMKilled", False))
        try:
            marker = await io_call(container.exec_run, ["cat", "/result/exit_code"])
        except APIError:
            # The process can exit/OOM between inspect and exec creation/start.
            # Inspect the terminal state before treating this as a Docker failure.
            container = await io_call(client.containers.get, container_id)
            state = container.attrs["State"]
            if state["Running"]:
                raise
            return ContainerExit(state.get("ExitCode"), oom_killed=state.get("OOMKilled", False))
        if marker.exit_code == 0:
            return ContainerExit(int(marker.output.decode().strip()))
        await asyncio.sleep(0.2)
    container = await io_call(client.containers.get, container_id)
    await io_call(container.kill)
    return ContainerExit(None, timed_out=True)


async def read_result_file(client, container_id, max_bytes):
    # tmpfs lives in the container mount namespace; get_archive cannot reliably
    # observe it. A fixed trusted reader returns at most the configured limit.
    program = """import os,stat,sys
fd=os.open('/result/result.json',os.O_RDONLY|os.O_NOFOLLOW)
info=os.fstat(fd)
limit=int(sys.argv[1])
if not stat.S_ISREG(info.st_mode) or info.st_size>limit: sys.exit(2)
with os.fdopen(fd,'rb') as stream: data=stream.read(limit+1)
if len(data)>limit: sys.exit(2)
sys.stdout.buffer.write(data)
"""
    container = await io_call(client.containers.get, container_id)
    result = await io_call(
        container.exec_run, ["python3", "-I", "-c", program, str(max_bytes)], stderr=False
    )
    if result.exit_code != 0:
        raise ValueError("Missing, oversized or unsafe result file")
    return result.output


async def list_managed_containers(client, settings, user_id=None):
    labels = [f"evalops.deployment={settings.deployment_id}"]
    if user_id is not None:
        labels.append(f"evalops.user={user_id}")
    containers = await io_call(client.containers.list, all=True, filters={"label": labels})
    return [_model(c) for c in containers]


async def wrap_evaluator_image(client, image):
    """Add the trusted runner as a cached image layer, not a writable host mount."""
    import hashlib

    runner = (Path(__file__).resolve().parent.parent / "grading" / "sandbox_runner.py").read_bytes()
    tag = "evalops-harness:" + hashlib.sha256(image.encode() + runner).hexdigest()[:32]

    def build():
        try:
            return client.images.get(tag).id
        except ImageNotFound:
            payload = io.BytesIO()
            with tarfile.open(fileobj=payload, mode="w") as archive:
                for name, data in [
                    ("Dockerfile", f"FROM {image}\nCOPY runner.py /runner.py\n".encode()),
                    ("runner.py", runner),
                ]:
                    entry = tarfile.TarInfo(name)
                    entry.size = len(data)
                    entry.mode = 0o444
                    archive.addfile(entry, io.BytesIO(data))
            payload.seek(0)
            result, _ = client.images.build(fileobj=payload, custom_context=True, tag=tag, rm=True)
            return result.id

    return await io_call(build)
