"""Authentication endpoints for EvalOps Backend."""

from __future__ import annotations

from typing import Any, Dict, Tuple

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from ...core.dependencies import get_current_session_and_student, require_csrf
from ...core.security import generate_session_credentials, verify_password
from ...db import (
    connect_db,
    create_session,
    delete_session,
    get_student_by_email,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginPayload(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(payload: LoginPayload, response: Response):
    with connect_db() as conn:
        student = get_student_by_email(conn, payload.email)
        if not student or not verify_password(student["password_hash"], payload.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "INVALID_CREDENTIALS", "message": "Email ou mot de passe incorrect"}},
            )

        raw_token, token_hash, csrf_token, expires_at = generate_session_credentials()
        create_session(conn, token_hash, student["id"], csrf_token, expires_at)

    response.set_cookie(
        key="session_token",
        value=raw_token,
        httponly=True,
        samesite="strict",
        path="/",
    )

    return {
        "student": {
            "id": student["id"],
            "email": student["email"],
            "role": student["role"],
        },
        "csrf_token": csrf_token,
    }


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(require_csrf)):
    sess, _ = auth_data
    with connect_db() as conn:
        delete_session(conn, sess["token_hash"])

    response.delete_cookie(key="session_token", path="/", httponly=True, samesite="strict")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me")
def get_me(auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(get_current_session_and_student)):
    sess, student = auth_data
    return {
        "id": student["id"],
        "email": student["email"],
        "role": student["role"],
        "csrf_token": sess["csrf_token"],
    }
