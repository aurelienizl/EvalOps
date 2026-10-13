"""Operation tracking and volume key injection endpoints for Container Manager."""

from __future__ import annotations

import logging

from fastapi import APIRouter, status

from shared.contracts import Identifier, ManagerOperation, ManagerSSHKeyRequest

from ...core.exceptions import http_error
from ...docker_runtime import ConflictError
from ...services.state import get_docker_runtime, require_runtime

logger = logging.getLogger("container_manager.api.operations")
router = APIRouter(prefix="/students", tags=["operations"])


@router.get("/{student_id}/operations/{operation_id}", response_model=ManagerOperation)
def get_operation_status(student_id: Identifier, operation_id: Identifier):
    """Inspects status of an in-flight operation for a student."""
    require_runtime()
    runtime = get_docker_runtime()
    operation = runtime.get_operation_info(student_id, operation_id)
    if operation is not None:
        return operation
    raise http_error(status.HTTP_404_NOT_FOUND, "OPERATION_NOT_FOUND", "Opération introuvable")


@router.post("/{student_id}/ssh-key")
def update_student_ssh_key(student_id: Identifier, req: ManagerSSHKeyRequest):
    """Updates student authorized_keys inside their named volume."""
    require_runtime()
    runtime = get_docker_runtime()
    try:
        runtime.update_student_volume_key(student_id, req.public_key)
        return {"status": "ok", "message": "SSH key updated successfully"}
    except ConflictError as exc:
        raise http_error(status.HTTP_409_CONFLICT, exc.code, str(exc))
    except Exception as e:
        logger.error(f"Error updating student SSH key: {e}", exc_info=True)
        raise http_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "VOLUME_UPDATE_FAILED", str(e))
