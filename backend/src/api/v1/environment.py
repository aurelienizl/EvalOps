"""Environment and grading runtime endpoints for EvalOps Backend."""

from __future__ import annotations

from typing import Any, Dict, Tuple

from fastapi import APIRouter, Depends, HTTPException, status

from ...core.dependencies import get_current_session_and_student, require_student_csrf
from ...state import get_runtime_manager

router = APIRouter(tags=["environment"])


def _require_manager():
    runtime_manager = get_runtime_manager()
    if not runtime_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "PLATFORM_PREPARING", "message": "Backend initialisation in progress"}},
        )
    return runtime_manager


@router.get("/environment")
def get_environment(auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(get_current_session_and_student)):
    _, student = auth_data
    return _require_manager().get_environment(student["id"])


@router.post("/exercises/{exercise_id}/start")
def start_exercise(
    exercise_id: str,
    auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(require_student_csrf),
):
    _, student = auth_data
    return _require_manager().start_environment(
        student_id=student["id"],
        exercise_id=exercise_id,
        ssh_public_key=student["ssh_public_key"] or "",
    )


@router.post("/environment/stop")
def stop_environment(auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(require_student_csrf)):
    _, student = auth_data
    return _require_manager().stop_environment(student["id"])


@router.post("/exercises/{exercise_id}/grade")
def grade_exercise(
    exercise_id: str,
    auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(require_student_csrf),
):
    _, student = auth_data
    return _require_manager().grade_environment(student["id"], exercise_id)
