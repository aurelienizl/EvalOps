"""Student development environment control endpoints for Container Manager."""

from __future__ import annotations

import logging

from fastapi import APIRouter, status

from shared.contracts import (
    Identifier,
    ManagerEnvironmentResponse,
    ManagerStartRequest,
    ManagerStopRequest,
)

from ...core.exceptions import http_error
from ...docker_runtime import ConflictError
from ...services.state import (
    get_docker_runtime,
    get_exercise_report,
    require_runtime,
)

logger = logging.getLogger("container_manager.api.environments")
router = APIRouter(prefix="/students", tags=["environments"])


@router.get("/{student_id}/environment", response_model=ManagerEnvironmentResponse)
def get_student_environment(student_id: Identifier):
    """Returns live environment status and SSH port if running."""
    require_runtime()
    runtime = get_docker_runtime()
    try:
        return runtime.get_environment_info(student_id)
    except Exception as exc:
        logger.exception("Error inspecting student environment")
        raise http_error(status.HTTP_502_BAD_GATEWAY, "ENVIRONMENT_STATUS_FAILED", str(exc))


@router.post("/{student_id}/start")
def start_student_environment(student_id: Identifier, req: ManagerStartRequest):
    """Spawns development container and mounts persistent workspace."""
    ex, report = get_exercise_report(
        req.exercise_id,
        "dev_image_id",
        "Les environnements sont en cours de préparation",
        "L'image de l'exercice n'est pas disponible",
    )
    runtime = get_docker_runtime()

    try:
        return runtime.start_dev_environment(
            student_id=student_id,
            operation_id=req.operation_id,
            exercise_id=req.exercise_id,
            exercise_name=ex.name,
            image_id=report["dev_image_id"],
            workspace_dir=ex.workspace_dir,
            ssh_public_key=req.ssh_public_key,
        )
    except ConflictError as e:
        raise http_error(status.HTTP_409_CONFLICT, e.code, str(e), operation_id=req.operation_id)
    except RuntimeError as e:
        msg = str(e)
        code = "SSH_PORTS_EXHAUSTED" if "SSH_PORTS_EXHAUSTED" in msg else "ENVIRONMENT_START_FAILED"
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE if code == "SSH_PORTS_EXHAUSTED" else status.HTTP_502_BAD_GATEWAY
        raise http_error(status_code, code, msg, operation_id=req.operation_id)
    except Exception as e:
        logger.error(f"Unexpected error starting environment: {e}", exc_info=True)
        raise http_error(
            status.HTTP_502_BAD_GATEWAY, "ENVIRONMENT_START_FAILED", str(e), operation_id=req.operation_id,
        )


@router.post("/{student_id}/stop")
def stop_student_environment(student_id: Identifier, req: ManagerStopRequest):
    """Stops student container and releases allocated SSH port."""
    require_runtime()
    runtime = get_docker_runtime()
    try:
        return runtime.stop_student_environment(student_id, req.operation_id)
    except ConflictError as e:
        raise http_error(status.HTTP_409_CONFLICT, e.code, str(e), operation_id=req.operation_id)
    except Exception as e:
        logger.error(f"Error stopping environment: {e}", exc_info=True)
        raise http_error(
            status.HTTP_502_BAD_GATEWAY, "ENVIRONMENT_STOP_FAILED", str(e), operation_id=req.operation_id,
        )
