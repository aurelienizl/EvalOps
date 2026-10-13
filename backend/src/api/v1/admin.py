"""Administrative and generic query endpoints for EvalOps Backend."""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from ...core.dependencies import Role, require_admin, require_admin_csrf
from ...core.security import hash_password
from ...db import (
    connect_db,
    create_student,
    get_platform_stats,
    get_student_by_email,
    get_student_by_id,
    list_all_evaluations,
    list_all_student_runtimes,
    list_users,
    update_student_role,
)
from ...state import get_runtime_manager
from .evaluations import format_evaluation_response

router = APIRouter(prefix="/admin", tags=["admin"])


class CreateUserPayload(BaseModel):
    email: str
    password: str
    role: Role = Role.STUDENT


class UpdateRolePayload(BaseModel):
    role: Role


@router.get("/users")
def get_users(
    search: Optional[str] = Query(None, description="Search by email substring"),
    role: Optional[str] = Query(None, description="Filter by role: student, admin"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(require_admin),
):
    """Generic query interface to search and list users with pagination."""
    with connect_db() as conn:
        rows, total = list_users(conn, search=search, role=role, limit=limit, offset=offset)

    users = [
        {
            "id": r["id"],
            "email": r["email"],
            "role": r["role"],
            "ssh_public_key": r["ssh_public_key"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]

    return {
        "items": users,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: CreateUserPayload,
    auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(require_admin_csrf),
):
    """Creates a new user with the specified role."""
    if len(payload.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": {"code": "INVALID_REQUEST", "message": "Le mot de passe doit comporter au moins 8 caractères"}},
        )

    email = payload.email.lower().strip()
    with connect_db() as conn:
        existing = get_student_by_email(conn, email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": {"code": "USER_ALREADY_EXISTS", "message": f"L'utilisateur '{payload.email}' existe déjà"}},
            )

        user_id = str(uuid.uuid4())
        pwd_hash = hash_password(payload.password)
        try:
            create_student(conn, user_id, email, pwd_hash, role=payload.role.value)
        except sqlite3.IntegrityError as exc:
            if exc.sqlite_errorcode != sqlite3.SQLITE_CONSTRAINT_UNIQUE:
                raise
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": {"code": "USER_ALREADY_EXISTS", "message": f"L'utilisateur '{email}' existe déjà"}},
            ) from exc

    return {
        "id": user_id,
        "email": email,
        "role": payload.role.value,
    }


@router.put("/users/{user_id}/role")
def change_user_role(
    user_id: str,
    payload: UpdateRolePayload,
    auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(require_admin_csrf),
):
    """Updates user permission role (e.g. promoting to admin or demoting to student)."""
    with connect_db() as conn:
        user = get_student_by_id(conn, user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": {"code": "USER_NOT_FOUND", "message": "Utilisateur introuvable"}},
            )
        update_student_role(conn, user_id, payload.role.value)

    return {
        "id": user_id,
        "role": payload.role.value,
        "message": f"Rôle mis à jour: {payload.role.value}",
    }


@router.get("/evaluations")
def get_all_evaluations(
    student_id: Optional[str] = Query(None),
    exercise_id: Optional[str] = Query(None),
    eval_status: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(require_admin),
):
    """Generic query interface to list and filter evaluation history across all students."""
    with connect_db() as conn:
        rows, total = list_all_evaluations(
            conn, student_id=student_id, exercise_id=exercise_id, eval_status=eval_status, limit=limit, offset=offset
        )

    return {
        "items": [format_evaluation_response(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/environments")
def get_all_environments(
    auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(require_admin),
):
    """Lists all active student operations and environments."""
    with connect_db() as conn:
        runtimes = list_all_student_runtimes(conn)

    return {
        "active_environments": [
            {
                "student_id": r["student_id"],
                "email": r["email"],
                "operation_id": r["operation_id"],
                "operation_type": r["operation_type"],
                "exercise_id": r["operation_exercise_id"],
                "started_at": r["operation_started_at"],
                "phase": r["phase"],
            }
            for r in runtimes
        ]
    }


@router.post("/environments/{student_id}/unlock")
def force_unlock_student(
    student_id: str,
    auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(require_admin_csrf),
):
    """Clears stale runtime state after verifying no worker is still running."""
    runtime_manager = get_runtime_manager()
    if not runtime_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "PLATFORM_PREPARING", "message": "Backend initialisation in progress"}},
        )
    runtime_manager.unlock_student(student_id)

    return {"status": "unlocked", "student_id": student_id}


@router.get("/stats")
def get_stats(
    auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(require_admin),
):
    """Aggregates platform statistics for admin monitoring."""
    with connect_db() as conn:
        stats = get_platform_stats(conn)
    return stats
