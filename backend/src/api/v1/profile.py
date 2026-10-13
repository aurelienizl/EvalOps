"""Profile endpoints for EvalOps Backend."""

from __future__ import annotations

from typing import Any, Dict, Tuple

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from ...core.dependencies import get_current_session_and_student, require_csrf
from ...core.security import (
    SSHKeyValidationError,
    hash_password,
    validate_and_normalize_ed25519_key,
    verify_password,
)
from ...db import (
    connect_db,
    delete_all_student_sessions,
    get_student_by_id,
    update_student_password,
    update_student_ssh_key,
)
from ...state import get_runtime_manager

router = APIRouter(prefix="/profile", tags=["profile"])


class UpdatePasswordPayload(BaseModel):
    current_password: str
    new_password: str


class UpdateSSHKeyPayload(BaseModel):
    public_key: str


@router.get("")
def get_profile(auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(get_current_session_and_student)):
    _, student = auth_data
    return {
        "email": student["email"],
        "role": student["role"],
        "ssh_public_key": student["ssh_public_key"],
    }


@router.put("/password", status_code=status.HTTP_204_NO_CONTENT)
def update_password(
    payload: UpdatePasswordPayload,
    response: Response,
    auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(require_csrf),
):
    _, student = auth_data
    if len(payload.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": {"code": "INVALID_REQUEST", "message": "Le mot de passe doit comporter au moins 8 caractères"}},
        )

    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        st = get_student_by_id(conn, student["id"])
        if not st or not verify_password(st["password_hash"], payload.current_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "INVALID_CREDENTIALS", "message": "Mot de passe actuel incorrect"}},
            )

        new_hash = hash_password(payload.new_password)
        update_student_password(conn, student["id"], new_hash)
        delete_all_student_sessions(conn, student["id"])

    response.delete_cookie(key="session_token", path="/", httponly=True, samesite="strict")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.put("/ssh-key")
def update_ssh_key(
    payload: UpdateSSHKeyPayload,
    auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(require_csrf),
):
    _, student = auth_data
    student_id = student["id"]
    runtime_manager = get_runtime_manager()

    if not runtime_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "PLATFORM_PREPARING", "message": "Backend initialisation in progress"}},
        )

    # Serialize key changes with environment operations.
    lock = runtime_manager.get_student_lock(student_id)
    if not lock.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": {"code": "OPERATION_IN_PROGRESS", "message": "Une opération est en cours"}},
        )

    try:
        try:
            normalized_key = validate_and_normalize_ed25519_key(payload.public_key)
        except SSHKeyValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": {"code": "INVALID_SSH_KEY", "message": str(e)}},
            )

        # Persist only after the manager confirms the volume was updated.
        runtime_manager.update_student_ssh_key(student_id, normalized_key)
        with connect_db() as conn:
            update_student_ssh_key(conn, student_id, normalized_key)

        return {"ssh_public_key": normalized_key}

    finally:
        lock.release()
