"""Courses and exercises catalog endpoints for EvalOps Backend."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from shared.contracts import Difficulty

from ...core.dependencies import get_current_session_and_student
from ...db import (
    check_evaluation_quota,
    connect_db,
    get_completed_exercise_ids,
)
from ...state import get_catalog, get_runtime_manager

router = APIRouter(tags=["courses"])


@router.get("/courses")
def get_courses(auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(get_current_session_and_student)):
    _, student = auth_data
    catalog = get_catalog()
    runtime_manager = get_runtime_manager()

    if not catalog or not runtime_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "PLATFORM_PREPARING", "message": "Backend initialisation in progress"}},
        )

    with connect_db() as conn:
        completed_ex_ids = get_completed_exercise_ids(conn, student["id"])

    mgr_cat = runtime_manager.get_manager_catalog()
    build_report = mgr_cat["build_report"] if mgr_cat.get("available", False) else {}

    courses_list = []
    for c in catalog.list_courses():
        total_exercises = len(c.exercises)
        completed_count = sum(1 for ex in c.exercises if ex.id in completed_ex_ids)
        earned_points = sum(ex.points for ex in c.exercises if ex.id in completed_ex_ids)
        max_points = sum(ex.points for ex in c.exercises)

        is_available = any(build_report.get(ex.id, {}).get("available", False) for ex in c.exercises)

        courses_list.append({
            "id": c.id,
            "name": c.name,
            "deadline": c.deadline_iso,
            "progress": {
                "completed": completed_count,
                "total": total_exercises,
            },
            "score": {
                "earned": earned_points,
                "maximum": max_points,
            },
            "completed": (completed_count == total_exercises and total_exercises > 0),
            "available": is_available,
        })

    return {"courses": courses_list}


@router.get("/courses/{course_id}")
def get_course_detail(
    course_id: str,
    auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(get_current_session_and_student),
):
    _, student = auth_data
    catalog = get_catalog()
    runtime_manager = get_runtime_manager()

    if not catalog or not runtime_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "PLATFORM_PREPARING", "message": "Backend initialisation in progress"}},
        )

    c = catalog.get_course(course_id)
    if not c:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "COURSE_NOT_FOUND", "message": "Cours introuvable"}},
        )

    with connect_db() as conn:
        completed_ex_ids = get_completed_exercise_ids(conn, student["id"])

    mgr_cat = runtime_manager.get_manager_catalog()
    build_report = mgr_cat["build_report"] if mgr_cat.get("available", False) else {}

    grouped_exercises: Dict[str, List[Dict[str, Any]]] = {difficulty.value: [] for difficulty in Difficulty}

    for ex in c.exercises:
        is_completed = ex.id in completed_ex_ids
        is_avail = build_report.get(ex.id, {}).get("available", False)
        grouped_exercises[ex.difficulty.value].append({
            "id": ex.id,
            "name": ex.name,
            "difficulty": ex.difficulty.value,
            "points": ex.points,
            "order": ex.order,
            "completed": is_completed,
            "available": is_avail,
        })

    return {
        "id": c.id,
        "name": c.name,
        "deadline": c.deadline_iso,
        "is_expired": c.is_expired(),
        "exercises_by_difficulty": grouped_exercises,
    }


@router.get("/exercises/{exercise_id}")
def get_exercise_detail(
    exercise_id: str,
    auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(get_current_session_and_student),
):
    _, student = auth_data
    catalog = get_catalog()
    runtime_manager = get_runtime_manager()
    if not catalog or not runtime_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "PLATFORM_PREPARING", "message": "Backend initialisation in progress"}},
        )

    ex = catalog.get_exercise(exercise_id)
    if not ex:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "EXERCISE_NOT_FOUND", "message": "Exercice introuvable"}},
        )

    course = catalog.get_course(ex.course_id)
    mgr_cat = runtime_manager.get_manager_catalog()
    build_report = mgr_cat["build_report"] if mgr_cat.get("available", False) else {}
    with connect_db() as conn:
        completed_ex_ids = get_completed_exercise_ids(conn, student["id"])
        evaluation_quota = check_evaluation_quota(
            conn, student["id"], exercise_id, ex.max_evaluations, ex.evaluation_window_minutes
        )

    return {
        "id": ex.id,
        "name": ex.name,
        "course_id": ex.course_id,
        "course_name": course.name if course else "",
        "course_deadline": course.deadline_iso if course else "",
        "difficulty": ex.difficulty.value,
        "points": ex.points,
        "completed": ex.id in completed_ex_ids,
        "available": build_report.get(ex.id, {}).get("available", False),
        "is_expired": bool(course and course.is_expired()),
        "evaluation_quota": evaluation_quota,
        "readme": ex.get_readme_content(),
        "resources": [
            {"id": r.id, "name": r.name} for r in ex.resources
        ],
    }


@router.get("/exercises/{exercise_id}/resources/{resource_id}")
def download_resource(
    exercise_id: str,
    resource_id: str,
    auth_data: Tuple[Dict[str, Any], Dict[str, Any]] = Depends(get_current_session_and_student),
):
    catalog = get_catalog()
    if not catalog:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "PLATFORM_PREPARING", "message": "Backend initialisation in progress"}},
        )

    ex = catalog.get_exercise(exercise_id)
    if not ex:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "EXERCISE_NOT_FOUND", "message": "Exercice introuvable"}},
        )

    file_path = ex.resolve_resource_file(resource_id)
    if not file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "RESOURCE_NOT_FOUND", "message": "Ressource introuvable ou chemin non autorisé"}},
        )

    return FileResponse(path=str(file_path), filename=file_path.name)
