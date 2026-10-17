"""Reset and run compose.yaml with its existing deployment variables."""

import json
from pathlib import Path
import subprocess
import docker
from .database import Database

ROOT = Path(__file__).resolve().parents[2]


class Deployment:
    def __init__(self):
        self.config = json.loads(self.compose("config", "--format", "json").stdout)
        self.settings = self.config["services"]["container_manager"]["environment"]
        self.deployment_id = self.settings["DEPLOYMENT_ID"]
        self.docker = docker.from_env(timeout=30)
        self.db = Database(self)
        self.built = False
        data = Path(self.settings["DATA_ROOT"])
        assert data.is_absolute() and data not in (Path("/"), ROOT), "Unsafe DATA_ROOT"
        assert any(
            v.get("source") == str(data) == v.get("target")
            for v in self.config["services"]["container_manager"]["volumes"]
        ), "DATA_ROOT must match the host mount"

    def compose(self, *args, input=None, check=True, timeout=1200):
        result = subprocess.run(
            ["docker", "compose", *args],
            cwd=ROOT,
            input=input,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if check and result.returncode:
            raise RuntimeError(result.stdout[-4000:] + result.stderr[-4000:])
        return result

    def containers(self, user_id=None, kind=None):
        labels = [f"evalops.deployment={self.deployment_id}"]
        if user_id:
            labels.append(f"evalops.user={user_id}")
        if kind:
            labels.append(f"evalops.kind={kind}")
        return self.docker.containers.list(all=True, filters={"label": labels})

    def service(self, name):
        container_id = self.compose("ps", "-q", name).stdout.strip()
        assert container_id, f"Service {name} is not running"
        return self.docker.containers.get(container_id)

    def clean(self):
        self.compose("down", "--volumes", "--remove-orphans")
        for container in self.containers():
            container.remove(force=True)
        for network in self.docker.networks.list(
            filters={"label": f"evalops.deployment={self.deployment_id}"}
        ):
            network.remove()
        if self.built:
            self.compose(
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "python",
                "container_manager",
                "-c",
                """
import os, shutil
from pathlib import Path
root = Path(os.environ['DATA_ROOT'])
for name in ('workspaces', 'keys', 'snapshots'):
    path = root / name
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)
""",
            )
            # compose run may recreate the project's network and empty volumes.
            self.compose("down", "--volumes", "--remove-orphans")

    def start(self):
        print(
            f"\nResetting {self.config['name']}: database, containers and managed runtime folders.",
            flush=True,
        )
        self.clean()
        self.compose("build", "backend", "container_manager")
        self.built = True
        self.clean()
        self.compose(
            "up", "-d", "--wait", "--wait-timeout", "1200", "db", "container_manager", "backend"
        )
        backend = self.service("backend")
        network = self.config["networks"]["default"]["name"]
        address = backend.attrs["NetworkSettings"]["Networks"][network]["IPAddress"]
        self.url = f"http://{address}:8080"
        assert {
            row["id"]
            for row in self.db.rows("SELECT id FROM exercises WHERE id IN ('hello-c','sum-c')")
        } == {"hello-c", "sum-c"}, "The example exercises are required"
        print("Backend and container manager ready; frontend remains stopped.", flush=True)

    def logs(self):
        return self.compose(
            "logs", "--tail", "50", "backend", "container_manager", check=False
        ).stdout

    def restart_manager(self):
        self.compose("restart", "container_manager")
        self.compose(
            "up", "-d", "--no-deps", "--wait", "--wait-timeout", "1200", "container_manager"
        )

    def close(self):
        try:
            self.clean()
        finally:
            self.docker.close()
