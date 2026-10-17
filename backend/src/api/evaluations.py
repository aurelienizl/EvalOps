"""Atomic grading reservation, evaluation history and owned code archives."""

import json
from uuid import UUID, uuid4
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.encoders import jsonable_encoder
from ..database.connection import transaction, lock_student
from .common import exercise, active_evaluation, check_quota, contained_file
from .dependencies import Database, Config, User, Limit, Offset

router = APIRouter(tags=["Evaluations"])


@router.post("/exercises/{exercise_id}/grade", status_code=202)
async def grade_exercise(exercise_id: str, pool: Database, user: User):
    async with transaction(pool) as c:
        await lock_student(c, user.id)
        ex = await exercise(c, exercise_id, open_required=True)
        env = await c.fetchrow("SELECT * FROM environments WHERE user_id=$1 FOR UPDATE", user.id)
        if (
            await active_evaluation(c, user.id)
            or env
            and env["status"] in ("starting", "stopping", "grading")
        ):
            raise HTTPException(409, "An operation is in progress; controls locked")
        if not env or env["status"] != "running" or env["exercise_id"] != exercise_id:
            raise HTTPException(409, "Start this exercise's environment before evaluating.")
        await check_quota(c, user.id, ex)
        evaluation_id = uuid4()
        await c.execute(
            "INSERT INTO evaluations(id,user_id,exercise_id,status) VALUES($1,$2,$3,'running')",
            evaluation_id,
            user.id,
            exercise_id,
        )
        await c.execute(
            """UPDATE environments SET status='grading',current_operation_id=$2,
            last_activity_at=now() WHERE user_id=$1""",
            user.id,
            evaluation_id,
        )
        await c.execute(
            "SELECT pg_notify('grade_queue',$1)", json.dumps(dict(evaluation_id=str(evaluation_id)))
        )
    url = f"/api/v1/evaluations/{evaluation_id}"
    return JSONResponse(
        jsonable_encoder(dict(id=evaluation_id, status="running", poll_url=url)),
        status_code=202,
        headers={"Location": url},
    )


@router.get("/exercises/{exercise_id}/evaluations")
async def list_evaluations(
    exercise_id: str, pool: Database, user: User, limit: Limit = 50, offset: Offset = 0
):
    rows = await pool.fetch(
        """SELECT id,exercise_id,status,is_success,passed_tests,total_tests,
        created_at,finished_at,error_code,error_message FROM evaluations WHERE user_id=$1 AND exercise_id=$2
        ORDER BY created_at DESC,id DESC LIMIT $3 OFFSET $4""",
        user.id,
        exercise_id,
        limit,
        offset,
    )
    total = await pool.fetchval(
        "SELECT count(*) FROM evaluations WHERE user_id=$1 AND exercise_id=$2", user.id, exercise_id
    )
    return dict(items=[dict(r) for r in rows], limit=limit, offset=offset, total=total)


@router.get("/evaluations/{evaluation_id}")
async def get_evaluation(evaluation_id: UUID, pool: Database, user: User):
    row = await pool.fetchrow(
        "SELECT * FROM evaluations WHERE id=$1 AND user_id=$2", evaluation_id, user.id
    )
    if row is None:
        raise HTTPException(404, "Evaluation not found")
    data = dict(row)
    data["snapshot_available"] = bool(data.pop("snapshot_archive_path"))
    tests = await pool.fetch(
        "SELECT name,status,return_code,stdout_diff,stderr_diff,execution_time_ms FROM evaluation_tests WHERE evaluation_id=$1 ORDER BY id",
        evaluation_id,
    )
    return dict(data, tests=[dict(t) for t in tests])


@router.get("/evaluations/{evaluation_id}/snapshot")
async def download_snapshot(evaluation_id: UUID, pool: Database, settings: Config, user: User):
    row = await pool.fetchrow(
        "SELECT snapshot_archive_path FROM evaluations WHERE id=$1 AND user_id=$2",
        evaluation_id,
        user.id,
    )
    if row is None or not row["snapshot_archive_path"]:
        raise HTTPException(404, "Snapshot not found")
    path = contained_file(settings.data_root, row["snapshot_archive_path"])
    return FileResponse(path, media_type="application/gzip", filename=f"{evaluation_id}.tar.gz")
