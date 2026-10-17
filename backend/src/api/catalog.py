"""Read-only catalog and authenticated attachment downloads."""

from uuid import UUID
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from .common import exercise, quota, contained_file
from .dependencies import Database, Config, User

router = APIRouter(tags=["Catalog"])


@router.get("/courses")
async def list_courses(pool: Database, user: User):
    rows = await pool.fetch(
        '''SELECT c.id,c.name,c.deadline,count(e.id)::int AS total_exercises,
        count(done.exercise_id)::int AS completed_exercises FROM courses c
        LEFT JOIN exercises e ON e.course_id=c.id
        LEFT JOIN user_completed_exercises done ON done.exercise_id=e.id AND done.user_id=$1
        GROUP BY c.id ORDER BY c.id COLLATE "C"''',
        user.id,
    )
    return dict(items=[dict(r) for r in rows])


@router.get("/courses/{course_id}")
async def get_course(course_id: str, pool: Database, user: User):
    row = await pool.fetchrow("SELECT id,name,deadline FROM courses WHERE id=$1", course_id)
    if row is None:
        raise HTTPException(404, "Course not found")
    exercises = await pool.fetch(
        '''SELECT e.id,e.name,e.difficulty,done.exercise_id IS NOT NULL AS is_completed
        FROM exercises e LEFT JOIN user_completed_exercises done ON done.exercise_id=e.id AND done.user_id=$1
        WHERE course_id=$2 ORDER BY e.difficulty,e.id COLLATE "C"''',
        user.id,
        course_id,
    )
    return dict(row, exercises=[dict(r) for r in exercises])


@router.get("/exercises/{exercise_id}")
async def get_exercise(exercise_id: str, pool: Database, user: User):
    async with pool.acquire() as c:
        ex = await exercise(c, exercise_id)
        resources = await c.fetch(
            "SELECT id,name FROM exercise_resources WHERE exercise_id=$1 ORDER BY name,id",
            exercise_id,
        )
        completed = await c.fetchval(
            "SELECT EXISTS(SELECT 1 FROM user_completed_exercises WHERE user_id=$1 AND exercise_id=$2)",
            user.id,
            exercise_id,
        )
        value = await quota(c, user.id, ex)
    return dict(
        id=ex["id"],
        name=ex["name"],
        course_id=ex["course_id"],
        difficulty=ex["difficulty"],
        subject=ex["subject"],
        deadline=ex["deadline"],
        is_completed=completed,
        quota=value,
        resources=[
            dict(r, download_url=f"/api/v1/exercises/{exercise_id}/resources/{r['id']}")
            for r in resources
        ],
    )


@router.get("/exercises/{exercise_id}/resources/{resource_id}")
async def download_resource(
    exercise_id: str, resource_id: UUID, pool: Database, settings: Config, user: User
):
    row = await pool.fetchrow(
        "SELECT file_path,name FROM exercise_resources WHERE id=$1 AND exercise_id=$2",
        resource_id,
        exercise_id,
    )
    if row is None:
        raise HTTPException(404, "Resource not found")
    path = contained_file(settings.courses_root, row["file_path"])
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")
