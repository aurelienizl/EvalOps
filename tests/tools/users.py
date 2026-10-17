"""User setup, API workflows and workspace snapshots shared by all scenarios."""

import io
import tarfile
from uuid import uuid4
from argon2 import PasswordHasher
from .api import Api
from .database import quote
from .ssh_client import SshClient
from .wait import eventually

PASSWORD = "evalops-development-test-password"
HELLO = '#include <stdio.h>\nint main(void){puts("Hello C");}\n'
SLOW_HELLO = '#include <stdio.h>\n#include <unistd.h>\nint main(void){sleep(2);puts("Hello C");}\n'
HANG = "int main(void){for(;;){}}\n"
SUM = '#include <stdio.h>\nint main(void){int a,b;if(scanf("%d %d",&a,&b)!=2)return 1;printf("%d\\n",a+b);}\n'


class Student:
    def __init__(self, deployment, directory, *, role="student", ssh_key=True):
        self.deployment = deployment
        self.id = str(uuid4())
        self.email = f"test-{self.id}@example.test"
        self.key, self.public_key = SshClient.generate_key(directory)
        deployment.db.execute(f"""INSERT INTO users(id,email,password_hash,role,ssh_key)
            VALUES({quote(self.id)},{quote(self.email)},{quote(PasswordHasher().hash(PASSWORD))},
            {quote(role)},{quote(self.public_key if ssh_key else None)});""")
        self.api = Api(deployment.url)
        self.api.login(self.email, PASSWORD)

    def state(self):
        return self.api.get("/environment").json()

    def wait_environment(self, status):
        def ready():
            state = self.state()
            env = state["environment"]
            return env if env and env["status"] == status and not state["locked"] else None

        return eventually(ready, description=f"student {self.id}: {status}")

    def ssh(self, environment):
        connection = environment.get("ssh") or {
            "host": self.deployment.config["services"]["backend"]["environment"]["SSH_HOST"],
            "port": environment["ssh_port"],
            "user": "student",
        }
        return SshClient(connection, self.key)

    def start(self, exercise="hello-c"):
        self.api.post(f"/exercises/{exercise}/start", expected=(200, 202))
        return self.ssh(self.wait_environment("running"))

    def stop(self):
        self.api.post("/environment/stop", expected=(200, 202))
        return self.wait_environment("stopped")

    def submit(self, exercise="hello-c"):
        return self.api.post(f"/exercises/{exercise}/grade", expected=202).json()["id"]

    def report(self, evaluation_id):
        def finished():
            report = self.api.get(f"/evaluations/{evaluation_id}").json()
            return report if report["finished_at"] else None

        report = eventually(finished, timeout=180, description=f"report {evaluation_id}")
        self.wait_environment("stopped")
        assert not self.deployment.containers(self.id)
        return report

    def snapshot(self, evaluation_id):
        response = self.api.get(f"/evaluations/{evaluation_id}/snapshot")
        with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as archive:
            return {
                item.name: archive.extractfile(item).read() for item in archive if item.isfile()
            }

    def close(self):
        try:

            def idle():
                env = self.deployment.db.environment(self.id)
                return not env or env["status"] in ("running", "stopped")

            eventually(idle, timeout=180, description=f"cleanup {self.id}")
            env = self.deployment.db.environment(self.id)
            if env and env["status"] == "running":
                self.deployment.db.stop(self.id)
            assert not self.deployment.containers(self.id)
        finally:
            self.api.close()
