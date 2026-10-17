"""Validated Container Manager configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import re


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    courses_root: Path
    data_root: Path
    deployment_id: str
    shared_gid: int = field(default_factory=os.getgid)
    ssh_bind_address: str = "0.0.0.0"
    ssh_port_min: int = 20000
    ssh_port_max: int = 30000
    health_host: str = "0.0.0.0"
    health_port: int = 8001
    poll_interval_seconds: float = 1.0
    stop_grace_seconds: int = 10
    container_cpus: float = 1.0
    container_memory_bytes: int = 512 * 1024 * 1024
    container_pids_limit: int = 128
    max_result_bytes: int = 1024 * 1024
    environment_ttl_seconds: int = 7200
    max_workspace_bytes: int = 100 * 1024 * 1024
    max_workspace_files: int = 10000


def load_settings() -> Settings:
    deployment = os.environ.get("DEPLOYMENT_ID", "evalops")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", deployment):
        raise ValueError("Invalid DEPLOYMENT_ID")
    values = dict(
        database_url=os.environ["DATABASE_URL"],
        courses_root=Path(os.environ.get("COURSES_ROOT", "courses")).resolve(),
        data_root=Path(os.environ.get("DATA_ROOT", "/var/lib/evalops")).resolve(),
        deployment_id=deployment,
        health_host=os.environ.get("HEALTH_HOST", "0.0.0.0"),
        shared_gid=int(os.environ.get("DATA_SHARED_GID", str(os.getgid()))),
        ssh_bind_address=os.environ.get("SSH_BIND_ADDRESS", "0.0.0.0"),
    )
    for name in (
        "ssh_port_min",
        "ssh_port_max",
        "health_port",
        "stop_grace_seconds",
        "environment_ttl_seconds",
        "max_workspace_bytes",
        "max_workspace_files",
        "max_result_bytes",
    ):
        if name.upper() in os.environ:
            values[name] = int(os.environ[name.upper()])
    if "POLL_INTERVAL_SECONDS" in os.environ:
        values["poll_interval_seconds"] = float(os.environ["POLL_INTERVAL_SECONDS"])
    settings = Settings(**values)
    if not 1024 <= settings.ssh_port_min <= settings.ssh_port_max <= 65535:
        raise ValueError("Invalid SSH port range")
    if settings.poll_interval_seconds <= 0:
        raise ValueError("Invalid poll interval")
    for name, value in values.items():
        if isinstance(value, int) and value <= 0:
            raise ValueError(f"Invalid positive setting: {name}")
    return settings
