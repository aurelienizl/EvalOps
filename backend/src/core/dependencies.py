"""FastAPI dependencies for authentication, CSRF, and role-based permissions."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional, Tuple

from fastapi import Cookie, Depends, Header, HTTPException, Request, status

from ..db import (
    cleanup_expired_sessions,
    connect_db,
    get_session,
    get_student_by_id,
)
from .security import hash_session_token


class Role(str, Enum):
    STUDENT = "student"
    ADMIN = "admin"


def get_current_session_and_student(
    session_token: Optional[str] = Cookie(None),
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Validates session cookie, refreshes cleanup, and retrieves the authenticated student/user."""
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "AUTHENTICATION_REQUIRED", "message": "Authentification requise"}},
        )

    token_hash = hash_session_token(session_token)
    with connect_db() as conn:
        cleanup_expired_sessions(conn)
        sess = get_session(conn, token_hash)
        if not sess:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "AUTHENTICATION_REQUIRED", "message": "Session expirée ou invalide"}},
            )
        student = get_student_by_id(conn, sess["student_id"])
        if not student:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "AUTHENTICATION_REQUIRED", "message": "Compte introuvable"}},
            )
        return dict(sess), dict(student)


def get_current_user(
    auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(get_current_session_and_student),
) -> Dict[str, Any]:
    """Shortcut dependency returning only the user dictionary."""
    _, student = auth_data
    return student


def require_csrf(
    request: Request,
    x_csrf_token: Optional[str] = Header(None),
    auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(get_current_session_and_student),
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Enforces CSRF token match for mutating state operations."""
    sess, student = auth_data
    if not x_csrf_token or x_csrf_token != sess["csrf_token"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "CSRF_INVALID", "message": "Jeton CSRF manquant ou invalide"}},
        )
    return sess, student


def require_admin(
    auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(get_current_session_and_student),
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Restricts access to administrators only."""
    sess, student = auth_data
    if student.get("role") != Role.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "FORBIDDEN", "message": "Droits administrateur requis"}},
        )
    return sess, student


def require_student_csrf(
    auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(require_csrf),
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Restricts environment mutations to students with a valid CSRF token."""
    _, student = auth_data
    if student.get("role") != Role.STUDENT.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "FORBIDDEN", "message": "Les environnements sont réservés aux étudiants"}},
        )
    return auth_data


def require_admin_csrf(
    auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(require_csrf),
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Enforces both CSRF verification and admin privileges for mutating administrative endpoints."""
    sess, student = auth_data
    if student.get("role") != Role.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "FORBIDDEN", "message": "Droits administrateur requis"}},
        )
    return sess, student
