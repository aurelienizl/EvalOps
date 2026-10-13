"""Process-local manager state and endpoint readiness checks."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from fastapi import status

from shared.catalog import Catalog, Exercise

from ..core.exceptions import http_error

if TYPE_CHECKING:
    from ..builds import BuildManager
    from ..docker_runtime import DockerRuntime

_instance_id = str(uuid.uuid4())[:8]
_catalog: Catalog | None = None
_build_manager: BuildManager | None = None
_docker_runtime: DockerRuntime | None = None
_startup_error: str | None = None


def get_instance_id() -> str:
    return _instance_id


def get_startup_error() -> str | None:
    return _startup_error


def set_startup_error(error: str | None) -> None:
    global _startup_error
    _startup_error = error


def get_catalog() -> Catalog | None:
    return _catalog


def set_catalog(catalog: Catalog | None) -> None:
    global _catalog
    _catalog = catalog


def get_build_manager() -> BuildManager | None:
    return _build_manager


def set_build_manager(manager: BuildManager | None) -> None:
    global _build_manager
    _build_manager = manager


def get_docker_runtime() -> DockerRuntime | None:
    return _docker_runtime


def set_docker_runtime(runtime: DockerRuntime | None) -> None:
    global _docker_runtime
    _docker_runtime = runtime


def require_runtime(require_builds: bool = False) -> None:
    if _docker_runtime is None or (require_builds and _build_manager is None):
        raise http_error(status.HTTP_503_SERVICE_UNAVAILABLE, "MANAGER_UNAVAILABLE", "Runtime not initialized")


def get_exercise_report(
    exercise_id: str, image_key: str, preparing_message: str, unavailable_message: str,
) -> tuple[Exercise, dict[str, Any]]:
    require_runtime(require_builds=True)
    if not _build_manager.is_ready:
        raise http_error(status.HTTP_503_SERVICE_UNAVAILABLE, "PLATFORM_PREPARING", preparing_message)
    if _catalog is None:
        raise http_error(status.HTTP_503_SERVICE_UNAVAILABLE, "MANAGER_UNAVAILABLE", "Catalog not initialized")
    exercise = _catalog.get_exercise(exercise_id)
    if exercise is None:
        raise http_error(status.HTTP_404_NOT_FOUND, "EXERCISE_NOT_FOUND", "Exercice introuvable")
    report = _build_manager.report.get(exercise_id, {})
    if not report.get("available") or not report.get(image_key):
        raise http_error(status.HTTP_503_SERVICE_UNAVAILABLE, "EXERCISE_UNAVAILABLE", unavailable_message)
    return exercise, report
