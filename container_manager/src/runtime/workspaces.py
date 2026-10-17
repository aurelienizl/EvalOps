"""Persistent workspaces and manager-owned SSH material."""

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID
import os
import stat
import shutil
import tarfile
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PrivateFormat,
    PublicFormat,
    NoEncryption,
)


@dataclass(frozen=True)
class DevelopmentWorkspace:
    directory: Path
    authorized_key: Path


def _contained(root, path):
    root = root.resolve()
    if not path.resolve().is_relative_to(root):
        raise ValueError("Workspace path escapes data root")
    for parent in (path, *path.parents):
        if parent == root.parent:
            break
        if parent.is_symlink():
            raise ValueError("Symlink in managed path")
    return path


def workspace_path(settings, user_id, exercise):
    return _contained(
        settings.data_root,
        settings.data_root / "workspaces" / str(UUID(str(user_id))) / exercise["id"],
    )


def prepare_development_workspace(settings, user_id, exercise, public_key):
    path = workspace_path(settings, user_id, exercise)
    new = not path.exists()
    path.mkdir(parents=True, exist_ok=True)
    if new:
        os.chown(path, 1000, 1000)
        path.chmod(0o750)
        for resource in exercise.get("resources", []):
            source = _contained(
                settings.courses_root, settings.courses_root / resource["file_path"]
            )
            target = path / source.name
            if source.is_file() and not target.exists():
                shutil.copyfile(source, target)
                os.chown(target, 1000, 1000)
    keys = _contained(
        settings.data_root, settings.data_root / "keys" / str(user_id) / exercise["id"]
    )
    keys.mkdir(parents=True, exist_ok=True)
    keys.chmod(0o755)
    keyfile = keys / "authorized_keys"
    temporary = keys / "authorized_keys.tmp"
    temporary.write_text(public_key.strip() + "\n")
    temporary.chmod(0o644)
    temporary.replace(keyfile)
    hostkey = keys / "host_key"
    if not hostkey.exists():
        key = ed25519.Ed25519PrivateKey.generate()
        hostkey.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption()))
        hostkey.chmod(0o600)
        (keys / "host_key.pub").write_bytes(
            key.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH)
        )
    (keys / "sshd_config").write_text("""Port 22
HostKey /etc/training/host_key
AuthorizedKeysFile /etc/training/authorized_keys/%u
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AuthenticationMethods publickey
PermitEmptyPasswords no
UsePAM no
StrictModes yes
AllowUsers student
Subsystem sftp internal-sftp
AllowTcpForwarding no
AllowAgentForwarding no
PermitTunnel no
X11Forwarding no
ClientAliveInterval 30
ClientAliveCountMax 5
""")
    return DevelopmentWorkspace(path, keyfile)


def require_grading_workspace(settings, user_id, exercise):
    path = workspace_path(settings, user_id, exercise)
    if not path.is_dir():
        raise ValueError("No saved workspace for this exercise")
    return path


def archive_workspace(settings, evaluation_id, workspace):
    directory = _contained(
        settings.data_root, settings.data_root / "snapshots" / str(evaluation_id)
    )
    directory.mkdir(parents=True, exist_ok=True)
    os.chown(directory, -1, settings.shared_gid)
    directory.chmod(0o750)
    temporary = directory / "workspace.tmp"
    destination = directory / "workspace.tar.gz"
    count = total = 0
    with tarfile.open(temporary, "w:gz", dereference=False) as archive:
        for base, dirs, files in os.walk(workspace, followlinks=False):
            for name in sorted(dirs + files):
                path = Path(base) / name
                info = path.lstat()
                if (
                    not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
                    or info.st_nlink > 1
                    and stat.S_ISREG(info.st_mode)
                ):
                    raise ValueError("Workspace contains links or special files")
                count += 1
                total += info.st_size if path.is_file() else 0
                if count > settings.max_workspace_files or total > settings.max_workspace_bytes:
                    raise ValueError("Workspace exceeds grading size limits")
                archive.add(
                    path,
                    arcname=str(Path("workspace") / path.relative_to(workspace)),
                    recursive=False,
                )
    os.chown(temporary, -1, settings.shared_gid)
    temporary.chmod(0o640)
    temporary.replace(destination)
    return destination.relative_to(settings.data_root)
