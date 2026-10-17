"""Operator views; runtime cleanup goes through the same durable stop protocol."""

from typing import Literal
from uuid import UUID
from fastapi import APIRouter
from .environments import request_stop
from .dependencies import Database, Admin, Limit, Offset

router = APIRouter(prefix="/admin", tags=["Administration"])


@router.get("/stats")
async def get_stats(pool: Database, user: Admin):
    return dict(
        await pool.fetchrow("""SELECT
        (SELECT count(*) FROM users) AS users,
        (SELECT count(*) FROM environments WHERE status<>'stopped') AS active_environments,
        count(*) AS evaluations,count(*) FILTER(WHERE is_success) AS successful_evaluations,
        count(*) FILTER(WHERE status='running' AND finished_at IS NULL) AS pending_evaluations FROM evaluations""")
    )


@router.get("/environments")
async def list_environments(pool: Database, user: Admin, limit: Limit = 50, offset: Offset = 0):
    rows = await pool.fetch(
        """SELECT e.user_id,u.email,e.exercise_id,e.status,e.ssh_port,e.current_operation_id,
        e.last_activity_at,e.expires_at FROM environments e JOIN users u ON u.id=e.user_id
        WHERE e.status<>'stopped' ORDER BY e.last_activity_at,e.user_id LIMIT $1 OFFSET $2""",
        limit,
        offset,
    )
    total = await pool.fetchval("SELECT count(*) FROM environments WHERE status<>'stopped'")
    return dict(items=[dict(r) for r in rows], limit=limit, offset=offset, total=total)


@router.post("/environments/{user_id}/clear")
async def clear_environment(user_id: UUID, pool: Database, user: Admin):
    return await request_stop(pool, user_id)


@router.get("/evaluations")
async def list_evaluations(
    pool: Database,
    user: Admin,
    user_id: UUID | None = None,
    exercise_id: str | None = None,
    status: Literal["running", "completed", "failed", "timeout"] | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
):
    where = "($1::uuid IS NULL OR e.user_id=$1) AND ($2::text IS NULL OR e.exercise_id=$2) AND ($3::text IS NULL OR e.status::text=$3)"
    rows = await pool.fetch(
        f"""SELECT e.id,e.user_id,u.email,e.exercise_id,e.status,e.is_success,e.created_at,e.finished_at,
        e.error_code,e.error_message FROM evaluations e JOIN users u ON u.id=e.user_id WHERE {where}
        ORDER BY e.created_at DESC,e.id DESC LIMIT $4 OFFSET $5""",
        user_id,
        exercise_id,
        status,
        limit,
        offset,
    )
    total = await pool.fetchval(
        f"SELECT count(*) FROM evaluations e WHERE {where}", user_id, exercise_id, status
    )
    return dict(items=[dict(r) for r in rows], limit=limit, offset=offset, total=total)
