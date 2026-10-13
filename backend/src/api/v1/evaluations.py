"""Evaluation history and snapshot endpoints for EvalOps Backend."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ...core.dependencies import get_current_session_and_student
from ...db import (
    connect_db,
    get_evaluation,
    list_student_evaluations,
)
from ...state import get_runtime_manager

router = APIRouter(tags=["evaluations"])


def format_evaluation_response(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "student_id": row["student_id"],
        "exercise_id": row["exercise_id"],
        "exercise_name": row["exercise_name"],
        "exercise_points": row["exercise_points"],
        "status": row["status"],
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
        "passed": row["passed"],
        "total": row["total"],
        "percentage": row["percentage"],
        "tests": json.loads(row["tests_json"]) if row["tests_json"] else [],
        "error_code": row["error_code"],
        "error_message": row["error_message"],
    }


@router.get("/exercises/{exercise_id}/evaluations")
def get_exercise_evaluations(
    exercise_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(get_current_session_and_student),
):
    _, student = auth_data
    with connect_db() as conn:
        rows = list_student_evaluations(conn, student["id"], exercise_id=exercise_id, limit=limit, offset=offset)

    return {"evaluations": [format_evaluation_response(row) for row in rows]}


@router.get("/evaluations/{evaluation_id}")
def get_evaluation_detail(
    evaluation_id: str,
    auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(get_current_session_and_student),
):
    _, student = auth_data
    with connect_db() as conn:
        r = get_evaluation(conn, evaluation_id)
        if not r or r["student_id"] != student["id"]:
            # Strict 404 for unowned evaluation
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": {"code": "EVALUATION_NOT_FOUND", "message": "Évaluation introuvable"}},
            )

    return format_evaluation_response(r)


@router.get("/evaluations/{evaluation_id}/snapshot")
def get_evaluation_snapshot(
    evaluation_id: str,
    auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(get_current_session_and_student),
):
    _, student = auth_data
    runtime_manager = get_runtime_manager()
    if not runtime_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "PLATFORM_PREPARING", "message": "Backend initialisation in progress"}},
        )

    content = runtime_manager.get_evaluation_snapshot(student["id"], evaluation_id)
    return Response(
        content=content,
        media_type="application/gzip",
        headers={
            "Content-Disposition": f'attachment; filename="snapshot-{evaluation_id}.tar.gz"',
            "Content-Type": "application/gzip",
        },
    )
