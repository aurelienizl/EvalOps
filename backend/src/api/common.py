"""Small shared HTTP/SQL helpers, not a service abstraction layer."""

from pathlib import Path
from datetime import timedelta
import math
from fastapi import HTTPException


async def exercise(connection, exercise_id: str, *, open_required: bool = False):
    row = await connection.fetchrow(
        """SELECT e.*,c.deadline,now() AS db_now FROM exercises e
        JOIN courses c ON c.id=e.course_id WHERE e.id=$1""",
        exercise_id,
    )
    if row is None:
        raise HTTPException(404, "Exercise not found")
    if open_required and row["deadline"] is not None and row["deadline"] <= row["db_now"]:
        raise HTTPException(409, "Course deadline has passed")
    return row


async def active_evaluation(connection, user_id):
    return await connection.fetchrow(
        """SELECT * FROM evaluations WHERE user_id=$1
        AND status='running' AND finished_at IS NULL ORDER BY created_at,id LIMIT 1 FOR UPDATE""",
        user_id,
    )


async def quota(connection, user_id, ex) -> dict:
    dates = await connection.fetch(
        """SELECT created_at FROM evaluations
        WHERE user_id=$1 AND exercise_id=$2 AND created_at>now()-make_interval(mins=>$3)
        ORDER BY created_at,id""",
        user_id,
        ex["id"],
        ex["evaluation_window_minutes"],
    )
    used, maximum = len(dates), ex["max_evaluations"]
    retry = (
        (dates[used - maximum]["created_at"] + timedelta(minutes=ex["evaluation_window_minutes"]))
        if used >= maximum
        else None
    )
    return dict(
        limit=maximum,
        used=used,
        remaining=max(0, maximum - used),
        window_minutes=ex["evaluation_window_minutes"],
        retry_at=retry,
    )


async def check_quota(connection, user_id, ex):
    value = await quota(connection, user_id, ex)
    if not value["remaining"]:
        now = await connection.fetchval("SELECT now()")
        seconds = max(1, math.ceil((value["retry_at"] - now).total_seconds()))
        raise HTTPException(
            429, "Evaluation quota exhausted", headers={"Retry-After": str(seconds)}
        )


def contained_file(root: Path, stored: str) -> Path:
    path = Path(stored)
    target = path if path.is_absolute() else root / path
    if not target.resolve().is_relative_to(root.resolve()):
        raise HTTPException(404, "File not found")
    if any(p.is_symlink() for p in [target, *target.parents] if p != root.parent):
        raise HTTPException(404, "File not found")
    if not target.is_file():
        raise HTTPException(404, "File not found")
    return target
