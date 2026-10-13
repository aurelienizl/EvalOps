"""HTTP exception factory for consistent API error responses."""

from __future__ import annotations

from fastapi import HTTPException


def http_error(status_code: int, code: str, message: str, **details) -> HTTPException:
    """Builds a standardized HTTPException matching the EvalOps error format."""
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message, **details}},
    )
