"""Execute student commands with the system OpenSSH client."""

from pathlib import Path
import shlex
import subprocess


class SshClient:
    def __init__(self, connection, key):
        self.connection, self.key = connection, Path(key)

    @staticmethod
    def generate_key(directory):
        key = directory / "id_ed25519"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
        return key, key.with_suffix(".pub").read_text().strip()

    def run(self, command, *, input=None, terminal=False, timeout=20):
        result = subprocess.run(
            [
                "ssh",
                *(["-tt"] if terminal else []),
                "-i",
                str(self.key),
                "-o",
                "BatchMode=yes",
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                "-o",
                "ConnectTimeout=5",
                "-o",
                "ServerAliveInterval=5",
                "-o",
                "ServerAliveCountMax=2",
                "-p",
                str(self.connection["port"]),
                f"{self.connection['user']}@{self.connection['host']}",
                command,
            ],
            input=input,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        assert result.returncode == 0, (
            f"SSH {command}: {result.stderr[-1000:]} {result.stdout[-1000:]}"
        )
        return result.stdout

    def write(self, path, content):
        self.run(f"cat > {shlex.quote(path)}", input=content)
