"""Fresh Docker services and accounts for the capacity simulation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

import docker
import httpx
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

REPOSITORY = Path(__file__).resolve().parents[2]
PASSWORD = "Simulation123!"


@dataclass
class SimulationStudent:
    id: str
    name: str
    email: str
    client: httpx.Client
    ssh_public_key: str
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class SimulationInstance:
    students: list[SimulationStudent]
    backend_url: str
    platform_instance: str
    project: str
    run_id: str
    docker_client: docker.DockerClient
    courses_path: Path
    artifacts_path: Path
    compose_arguments: list[str]
    compose_environment: dict[str, str]

    def compose(
        self, *arguments: str, input_text: str | None = None, timeout: int = 300
    ) -> str:
        result = subprocess.run(
            [*self.compose_arguments, *arguments],
            cwd=REPOSITORY,
            env=self.compose_environment,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        with (self.artifacts_path / "compose.log").open(
            "a", encoding="utf-8"
        ) as stream:
            stream.write(f"$ docker compose {' '.join(arguments)}\n{result.stdout}\n")
        if result.returncode:
            raise RuntimeError(
                f"Docker Compose failed: {' '.join(arguments)}\n{result.stdout}"
            )
        return result.stdout

    def query(self, sql: str, parameters: tuple = ()) -> list[dict]:
        """Inspect this run's SQLite database without changing application state."""
        script = (
            "import json,sqlite3,sys; "
            "payload=json.load(sys.stdin); "
            "connection=sqlite3.connect('file:/data/app.db?mode=ro',uri=True); "
            "connection.row_factory=sqlite3.Row; "
            "rows=connection.execute(payload['sql'],payload['parameters']).fetchall(); "
            "print(json.dumps([dict(row) for row in rows])); connection.close()"
        )
        return json.loads(
            self.compose(
                "exec",
                "-T",
                "backend",
                "python",
                "-c",
                script,
                input_text=json.dumps({"sql": sql, "parameters": parameters}),
            )
        )


def _authenticate(student: SimulationStudent) -> None:
    login = student.client.post(
        "/api/v1/auth/login", json={"email": student.email, "password": PASSWORD}
    )
    assert login.status_code == 200, f"Login failed for {student.name}: {login.text}"
    student.headers = {"X-CSRF-Token": login.json()["csrf_token"]}
    key = student.client.put(
        "/api/v1/profile/ssh-key",
        headers=student.headers,
        json={"public_key": student.ssh_public_key},
    )
    assert key.status_code == 200, (
        f"SSH key setup failed for {student.name}: {key.text}"
    )


def _cleanup_resources(instance: SimulationInstance) -> None:
    """Delete only resources labelled for this run, then its Compose volumes."""
    errors = []
    filters = {
        "label": [
            "platform.app=devops-eval",
            f"platform.instance={instance.platform_instance}",
        ]
    }
    # Stop queued work before removing resources so no evaluator appears afterwards.
    try:
        instance.compose(
            "stop", "--timeout", "10", "backend", "container_manager", timeout=60
        )
    except Exception as exc:
        errors.append(str(exc))
    try:
        for container in instance.docker_client.containers.list(
            all=True, filters=filters, ignore_removed=True
        ):
            try:
                container.remove(force=True)
            except docker.errors.NotFound:
                pass
            except Exception as exc:
                errors.append(str(exc))
        for volume in instance.docker_client.volumes.list(filters=filters):
            try:
                volume.remove(force=True)
            except docker.errors.NotFound:
                pass
            except Exception as exc:
                errors.append(str(exc))
    except Exception as exc:
        errors.append(str(exc))
    try:
        instance.compose("down", "--volumes", "--remove-orphans", timeout=180)
    except Exception as exc:
        errors.append(str(exc))
    try:
        containers = instance.docker_client.containers.list(
            all=True, filters=filters, ignore_removed=True
        )
        volumes = instance.docker_client.volumes.list(filters=filters)
        if containers or volumes:
            errors.append(
                "Resources remain after cleanup: "
                + ", ".join(resource.name for resource in [*containers, *volumes])
            )
    except Exception as exc:
        errors.append(str(exc))
    if errors:
        raise RuntimeError("Simulation cleanup failed: " + "; ".join(errors))


@contextmanager
def create_simulation_instance(
    artifacts_path: Path, student_count: int
) -> Iterator[SimulationInstance]:
    run_id = uuid.uuid4().hex[:8]
    project = f"evalops-sim-{run_id}"
    courses_path = artifacts_path / "courses"
    shutil.copytree(REPOSITORY / "courses" / "examples", courses_path / "examples")
    manifest_path = courses_path / "examples" / "course.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["deadline"] = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )

    environment = dict(os.environ)
    environment["SIMULATION_COURSES_PATH"] = str(courses_path)
    environment["SIMULATION_PLATFORM_INSTANCE"] = project
    instance = SimulationInstance(
        students=[],
        backend_url="",
        platform_instance=project,
        project=project,
        run_id=run_id,
        docker_client=docker.from_env(timeout=180),
        courses_path=courses_path,
        artifacts_path=artifacts_path,
        compose_arguments=[
            "docker",
            "compose",
            "--project-name",
            project,
            "--file",
            str(REPOSITORY / "compose.yaml"),
            "--file",
            str(Path(__file__).with_name("compose.simulation.yaml")),
        ],
        compose_environment=environment,
    )
    try:
        configuration = json.loads(instance.compose("config", "--format", "json"))
        manager_environment = configuration["services"]["container_manager"][
            "environment"
        ]
        available_ports = (
            int(manager_environment["SSH_PORT_MAX"])
            - int(manager_environment["SSH_PORT_MIN"])
            + 1
        )
        if student_count > available_ports:
            raise ValueError(
                f"{student_count} students need more than the configured {available_ports} SSH ports; "
                "increase SSH_PORT_MAX before running this simulation"
            )
        instance.compose(
            "up",
            "--detach",
            "--build",
            "--wait",
            "--wait-timeout",
            "300",
            "backend",
            "container_manager",
            timeout=1200,
        )
        backend_id = instance.compose("ps", "--quiet", "backend").strip()
        backend = instance.docker_client.containers.get(backend_id)
        address = next(
            network["IPAddress"]
            for network in backend.attrs["NetworkSettings"]["Networks"].values()
            if network.get("IPAddress")
        )
        instance.backend_url = f"http://{address}:8000"
        readiness = httpx.get(f"{instance.backend_url}/api/v1/ready", timeout=10)
        assert readiness.status_code == 200, (
            f"Simulation backend is not ready: {readiness.text}"
        )

        accounts = [
            {
                "id": f"sim-{run_id}-{index:04d}",
                "email": f"student-{index}@simulation.invalid",
            }
            for index in range(student_count)
        ]
        seed_script = (
            "import json,sys; "
            "from backend.src.core.security import hash_password; "
            "from backend.src.db import connect_db,create_student; "
            "accounts=json.load(sys.stdin); "
            f"password_hash=hash_password({PASSWORD!r}); "
            "\nwith connect_db() as connection:\n"
            "    for account in accounts:\n"
            "        create_student(connection,account['id'],account['email'],password_hash)\n"
        )
        instance.compose(
            "exec",
            "-T",
            "backend",
            "python",
            "-c",
            seed_script,
            input_text=json.dumps(accounts),
        )
        for index, account in enumerate(accounts):
            public_key = (
                ed25519.Ed25519PrivateKey.generate()
                .public_key()
                .public_bytes(
                    encoding=serialization.Encoding.OpenSSH,
                    format=serialization.PublicFormat.OpenSSH,
                )
                .decode("ascii")
            )
            instance.students.append(
                SimulationStudent(
                    id=account["id"],
                    name=f"Student {index + 1}",
                    email=account["email"],
                    client=httpx.Client(
                        base_url=instance.backend_url,
                        timeout=httpx.Timeout(360, connect=10),
                    ),
                    ssh_public_key=public_key,
                )
            )
        # Authenticate in small batches: each Argon2 password check allocates 64 MB.
        with ThreadPoolExecutor(max_workers=min(student_count, 8)) as executor:
            list(executor.map(_authenticate, instance.students))
        yield instance
    finally:
        try:
            (artifacts_path / "services.log").write_text(
                instance.compose("logs", "--no-color", timeout=60),
                encoding="utf-8",
            )
        except Exception as exc:
            (artifacts_path / "services.log").write_text(str(exc), encoding="utf-8")
        for student in instance.students:
            student.client.close()
        try:
            _cleanup_resources(instance)
        finally:
            instance.docker_client.close()
