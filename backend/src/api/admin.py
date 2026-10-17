"""Teacher views over existing accounts, progress and runtime records."""

from typing import Literal
from uuid import UUID
from fastapi import APIRouter, HTTPException, Query
from .environments import request_stop
from .evaluations import evaluation_report
from .dependencies import Database, Admin, Limit, Offset

router = APIRouter(prefix="/admin", tags=["Administration"])


@router.get("/stats")
async def get_stats(pool: Database, user: Admin):
    return dict(
        await pool.fetchrow("""SELECT
        (SELECT count(*) FROM users) AS users,
        (SELECT count(*) FROM users WHERE role='student') AS students,
        (SELECT count(*) FROM environments WHERE status<>'stopped') AS active_environments,
        count(*) AS evaluations,count(*) FILTER(WHERE is_success) AS successful_evaluations,
        count(*) FILTER(WHERE status='running' AND finished_at IS NULL) AS pending_evaluations FROM evaluations""")
    )


@router.get("/students")
async def list_students(
    pool: Database,
    user: Admin,
    search: str = Query(default="", max_length=255),
    course_id: str | None = None,
    user_id: UUID | None = None,
    limit: Limit = 25,
    offset: Offset = 0,
):
    # Aggregate only the requested page of students; the existing user/exercise
    # indexes support these lookups without loading evaluation history in the UI.
    where = "role='student' AND strpos(lower(email),lower($1))>0 AND ($2::uuid IS NULL OR id=$2)"
    rows = await pool.fetch(
        f"""WITH students AS (
            SELECT id,email FROM users WHERE {where}
            ORDER BY lower(email),id LIMIT $4 OFFSET $5
        )
        SELECT s.id,s.email,activity.submissions,activity.attempted_exercises,
            progress.validated_exercises,
            latest.id AS last_submission_id,latest.created_at AS last_submission_at,
            latest.status AS latest_status,latest.is_success AS latest_is_success,
            latest.exercise_id AS latest_exercise_id,latest.name AS latest_exercise_name,
            env.status AS environment_status,env.exercise_id AS environment_exercise_id,
            current_ex.name AS environment_exercise_name,env.expires_at
        FROM students s
        LEFT JOIN environments env ON env.user_id=s.id
        LEFT JOIN exercises current_ex ON current_ex.id=env.exercise_id
        LEFT JOIN LATERAL (
            SELECT count(*) AS submissions,count(DISTINCT v.exercise_id) AS attempted_exercises
            FROM evaluations v JOIN exercises x ON x.id=v.exercise_id
            WHERE v.user_id=s.id AND ($3::text IS NULL OR x.course_id=$3)
        ) activity ON true
        LEFT JOIN LATERAL (
            SELECT count(*) AS validated_exercises FROM user_completed_exercises done
            JOIN exercises x ON x.id=done.exercise_id
            WHERE done.user_id=s.id AND ($3::text IS NULL OR x.course_id=$3)
        ) progress ON true
        LEFT JOIN LATERAL (
            SELECT v.id,v.created_at,v.status,v.is_success,v.exercise_id,x.name
            FROM evaluations v JOIN exercises x ON x.id=v.exercise_id
            WHERE v.user_id=s.id AND ($3::text IS NULL OR x.course_id=$3)
            ORDER BY v.created_at DESC,v.id DESC LIMIT 1
        ) latest ON true
        ORDER BY lower(s.email),s.id""",
        search,
        user_id,
        course_id,
        limit,
        offset,
    )
    total = await pool.fetchval(f"SELECT count(*) FROM users WHERE {where}", search, user_id)
    total_exercises = await pool.fetchval(
        "SELECT count(*) FROM exercises WHERE $1::text IS NULL OR course_id=$1", course_id
    )
    return dict(
        items=[dict(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
        total_exercises=total_exercises,
    )


@router.get("/environments")
async def list_environments(
    pool: Database,
    user: Admin,
    limit: Limit = 50,
    offset: Offset = 0,
    search: str = Query(default="", max_length=255),
    course_id: str | None = None,
):
    where = "e.status<>'stopped' AND strpos(lower(u.email),lower($1))>0 AND ($2::text IS NULL OR x.course_id=$2)"
    joins = (
        "FROM environments e JOIN users u ON u.id=e.user_id JOIN exercises x ON x.id=e.exercise_id"
    )
    rows = await pool.fetch(
        f"""SELECT e.user_id,u.email,e.exercise_id,x.name AS exercise_name,e.status,
        e.ssh_port,e.current_operation_id,e.last_activity_at,e.expires_at {joins}
        WHERE {where} ORDER BY e.last_activity_at,e.user_id LIMIT $3 OFFSET $4""",
        search,
        course_id,
        limit,
        offset,
    )
    total = await pool.fetchval(f"SELECT count(*) {joins} WHERE {where}", search, course_id)
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
    outcome: Literal["validated", "unsuccessful", "grading", "timeout", "error"] | None = None,
    course_id: str | None = None,
    search: str = Query(default="", max_length=255),
    limit: Limit = 50,
    offset: Offset = 0,
):
    where = """($1::uuid IS NULL OR e.user_id=$1)
        AND ($2::text IS NULL OR e.exercise_id=$2)
        AND ($3::text IS NULL OR e.status::text=$3)
        AND ($4::text IS NULL
            OR ($4='validated' AND e.is_success)
            OR ($4='unsuccessful' AND e.status='completed' AND NOT e.is_success)
            OR ($4='grading' AND e.status='running')
            OR ($4='timeout' AND e.status='timeout')
            OR ($4='error' AND e.status='failed'))
        AND ($5::text IS NULL OR x.course_id=$5)
        AND strpos(lower(u.email),lower($6))>0"""
    joins = (
        "FROM evaluations e JOIN users u ON u.id=e.user_id JOIN exercises x ON x.id=e.exercise_id"
    )
    args = (user_id, exercise_id, status, outcome, course_id, search)
    rows = await pool.fetch(
        f"""SELECT e.id,e.user_id,u.email,e.exercise_id,x.name AS exercise_name,e.status,
        e.is_success,e.passed_tests,e.total_tests,e.created_at,e.finished_at,e.error_code,e.error_message
        {joins} WHERE {where} ORDER BY e.created_at DESC,e.id DESC LIMIT $7 OFFSET $8""",
        *args,
        limit,
        offset,
    )
    total = await pool.fetchval(f"SELECT count(*) {joins} WHERE {where}", *args)
    return dict(items=[dict(r) for r in rows], limit=limit, offset=offset, total=total)


@router.get("/evaluations/{evaluation_id}")
async def get_evaluation(evaluation_id: UUID, pool: Database, user: Admin):
    row = await pool.fetchrow(
        """SELECT e.*,u.email,x.name AS exercise_name FROM evaluations e
        JOIN users u ON u.id=e.user_id JOIN exercises x ON x.id=e.exercise_id WHERE e.id=$1""",
        evaluation_id,
    )
    if row is None:
        raise HTTPException(404, "Evaluation not found")
    return await evaluation_report(pool, row)
