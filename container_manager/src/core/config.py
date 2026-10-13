"""Environment configuration for Container Manager."""

from __future__ import annotations

import os

COURSES_PATH = os.environ.get("COURSES_PATH", "/courses")
PLATFORM_INSTANCE = os.environ.get("PLATFORM_INSTANCE", "evalops-prod")
SSH_HOST = os.environ.get("SSH_HOST", "localhost")
SSH_BIND_ADDRESS = os.environ.get("SSH_BIND_ADDRESS", "0.0.0.0")
SSH_PORT_MIN = int(os.environ.get("SSH_PORT_MIN", "22000"))
SSH_PORT_MAX = int(os.environ.get("SSH_PORT_MAX", "22999"))
APT_CACHE_URL = os.environ.get("APT_CACHE_URL", "").strip()
