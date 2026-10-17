"""Transactional start/stop admission. No Docker access in the API."""

import json
from uuid import uuid4
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from ..database.connection import transaction, lock_student
from .common import exercise, active_evaluation
from .dependencies import Database, Config, User

router = APIRouter(tags=["Environments"])


@router.get("/environment")
async def get_environment(pool: Database, settings: Config, user: User):
    row = await pool.fetchrow("SELECT * FROM environments WHERE user_id=$1", user.id)
    evaluation = await pool.fetchval(
        "SELECT id FROM evaluations WHERE user_id=$1 AND status='running' AND finished_at IS NULL LIMIT 1",
        user.id,
    )
    if row is None:
        return dict(environment=None, locked=bool(evaluation), evaluation_id=evaluation)
    locked = row["status"] in ("starting", "stopping", "grading") or bool(evaluation)
    ssh = None
    if row["status"] == "running" and not locked:
        ssh = dict(
            host=settings.ssh_host,
            port=row["ssh_port"],
            user="student",
            command=(
                "ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
                f"-p {row['ssh_port']} student@{settings.ssh_host}"
            ),
        )
    return dict(
        environment=dict(
            exercise_id=row["exercise_id"],
            status=row["status"],
            operation_id=row["current_operation_id"],
            expires_at=row["expires_at"],
            ssh=ssh,
        ),
        locked=locked,
        evaluation_id=evaluation,
    )


@router.post("/exercises/{exercise_id}/start")
async def start_environment(exercise_id: str, pool: Database, settings: Config, user: User):
    async with transaction(pool) as c:
        await lock_student(c, user.id)
        await exercise(c, exercise_id, open_required=True)
        env = await c.fetchrow("SELECT * FROM environments WHERE user_id=$1 FOR UPDATE", user.id)
        if await active_evaluation(c, user.id):
            raise HTTPException(409, "Grading in progress; controls locked")
        if env and env["status"] == "running" and env["exercise_id"] == exercise_id:
            return dict(status="running", poll_url="/api/v1/environment")
        if env and (env["status"] != "stopped" or env["container_id"] or env["ssh_port"]):
            raise HTTPException(
                409, "Stop the current environment and wait before starting another"
            )
        if not await c.fetchval("SELECT ssh_key FROM users WHERE id=$1", user.id):
            raise HTTPException(409, "Register an SSH public key first")
        await c.execute("SELECT pg_advisory_xact_lock(62002)")
        total = await c.fetchval(
            "SELECT count(*) FROM environments WHERE status<>'stopped' OR container_id IS NOT NULL"
        )
        if total >= settings.max_environments:
            raise HTTPException(503, "Environment capacity reached", headers={"Retry-After": "30"})
        operation = uuid4()
        await c.execute(
            """INSERT INTO environments(user_id,exercise_id,status,current_operation_id)
            VALUES($1,$2,'starting',$3) ON CONFLICT(user_id) DO UPDATE SET
            exercise_id=$2,status='starting',current_operation_id=$3,expires_at=NULL,last_activity_at=now()""",
            user.id,
            exercise_id,
            operation,
        )
        await c.execute(
            "SELECT pg_notify('environment_events',$1)", json.dumps(dict(user_id=str(user.id)))
        )
    return JSONResponse(
        jsonable_encoder(
            dict(status="starting", operation_id=operation, poll_url="/api/v1/environment")
        ),
        status_code=202,
        headers={"Location": "/api/v1/environment"},
    )


async def request_stop(pool, user_id):
    async with transaction(pool) as c:
        await lock_student(c, user_id)
        env = await c.fetchrow("SELECT * FROM environments WHERE user_id=$1 FOR UPDATE", user_id)
        if await active_evaluation(c, user_id) or env and env["status"] in ("grading", "starting"):
            raise HTTPException(409, "An operation is in progress; controls locked")
        if not env or env["status"] == "stopped" and not env["container_id"]:
            return dict(status="stopped")
        if env["status"] != "stopping":
            await c.execute(
                "UPDATE environments SET status='stopping',current_operation_id=$2,last_activity_at=now() WHERE user_id=$1",
                user_id,
                uuid4(),
            )
        await c.execute(
            "SELECT pg_notify('environment_events',$1)", json.dumps(dict(user_id=str(user_id)))
        )
    return JSONResponse(dict(status="stopping", poll_url="/api/v1/environment"), status_code=202)


@router.post("/environment/stop")
async def stop_environment(pool: Database, user: User):
    return await request_stop(pool, user.id)
