"""Readiness against the existing catalog schema."""

from fastapi import APIRouter, HTTPException
from .dependencies import Database

router = APIRouter(tags=["Health"])


@router.get("/healthz")
async def healthz(pool: Database):
    try:
        await pool.fetchval("SELECT count(*) FROM courses")
        return dict(status="ready")
    except Exception as exc:
        raise HTTPException(503, "Database unavailable") from exc
