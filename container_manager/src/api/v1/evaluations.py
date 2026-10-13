"""Evaluation and snapshot endpoints for Container Manager."""

from __future__ import annotations

import logging

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from shared.contracts import Identifier, ManagerGradeRequest, ManagerGradeResponse

from ...core.exceptions import http_error
from ...docker_runtime import ConflictError
from ...services.state import (
    get_docker_runtime,
    get_exercise_report,
    require_runtime,
)

logger = logging.getLogger("container_manager.api.evaluations")
router = APIRouter(prefix="/students", tags=["evaluations"])


@router.post("/{student_id}/grade", response_model=ManagerGradeResponse)
def grade_student_environment(student_id: Identifier, req: ManagerGradeRequest):
    """Executes sandboxed evaluator container against student workspace."""
    ex, report = get_exercise_report(
        req.exercise_id,
        "evaluator_image_id",
        "Les évaluateurs sont en cours de préparation",
        "L'évaluateur de cet exercice n'est pas disponible",
    )
    runtime = get_docker_runtime()

    try:
        return runtime.grade_student_exercise(
            student_id=student_id,
            operation_id=req.operation_id,
            exercise_id=req.exercise_id,
            evaluator_image_id=report["evaluator_image_id"],
            workspace_dir=ex.workspace_dir,
            timeout_seconds=ex.grade_timeout_seconds,
        )
    except ConflictError as e:
        raise http_error(status.HTTP_409_CONFLICT, e.code, str(e), operation_id=req.operation_id)
    except Exception as e:
        logger.error(f"Error grading environment: {e}", exc_info=True)
        raise http_error(
            status.HTTP_502_BAD_GATEWAY, "EVALUATOR_FAILED", str(e), operation_id=req.operation_id,
        )


@router.get("/{student_id}/evaluations/{operation_id}/snapshot")
def get_student_evaluation_snapshot(student_id: Identifier, operation_id: Identifier):
    """Streams tarball archive of student code captured at evaluation time."""
    require_runtime()
    runtime = get_docker_runtime()
    try:
        snapshot = runtime.open_student_snapshot(student_id, operation_id)
    except (OSError, ValueError):
        snapshot = None
    except Exception as exc:
        logger.exception("Error opening evaluation snapshot")
        raise http_error(status.HTTP_502_BAD_GATEWAY, "SNAPSHOT_ERROR", str(exc))
    if snapshot is None:
        raise http_error(status.HTTP_404_NOT_FOUND, "SNAPSHOT_NOT_FOUND", "Snapshot introuvable")

    def chunks():
        try:
            while chunk := snapshot.read(65536):
                yield chunk
        finally:
            snapshot.close()

    return StreamingResponse(
        chunks(),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="snapshot-{operation_id}.tar.gz"'},
        background=BackgroundTask(snapshot.close),
    )
