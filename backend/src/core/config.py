"""Environment configuration; runtime services never modify the schema."""

from dataclasses import dataclass, field
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    courses_root: Path
    data_root: Path
    ssh_host: str
    host: str = "0.0.0.0"
    port: int = 8080
    session_ttl_seconds: int = 43200
    cookie_name: str = "evalops-session"
    secure_cookie: bool = False
    max_environments: int = 50


def load_settings() -> Settings:
    database_url = os.environ["DATABASE_URL"]
    port = int(os.environ.get("PORT", "8080"))
    ssh_host = os.environ.get("SSH_HOST", "localhost")
    maximum = int(os.environ.get("MAX_ENVIRONMENTS", "50"))
    if not 1 <= port <= 65535 or maximum < 1:
        raise ValueError("Invalid port or environment capacity")
    return Settings(
        database_url,
        Path(os.environ.get("COURSES_ROOT", "courses")).resolve(),
        Path(os.environ.get("DATA_ROOT", "/var/lib/evalops")).resolve(),
        ssh_host,
        host=os.environ.get("API_HOST", "0.0.0.0"),
        port=port,
        max_environments=maximum,
        secure_cookie=os.environ.get("COOKIE_SECURE", "false").lower() == "true",
    )
