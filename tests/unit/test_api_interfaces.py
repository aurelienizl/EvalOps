"""HTTP interface regressions using an isolated database and mocked manager."""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.src.api.v1 import courses, environment, profile
from backend.src.app import app
from backend.src.core.security import SSHKeyValidationError, validate_and_normalize_ed25519_key
from backend.src.db import connect_db, get_student_by_id, update_student_role


@pytest.fixture
def api_client(tmp_db):
    # No lifespan: these tests do not build images or contact Docker.
    client = TestClient(app, raise_server_exceptions=True)
    try:
        yield client
    finally:
        client.close()


def login(client):
    response = client.post("/api/v1/auth/login", json={"email": "alice@ecole.fr", "password": "Password123!"})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def test_logout_expires_cookie_and_invalidates_session(api_client):
    headers = login(api_client)
    cookie = api_client.cookies.get("session_token")
    response = api_client.post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 204
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert api_client.cookies.get("session_token") is None
    api_client.cookies.set("session_token", cookie)
    assert api_client.get("/api/v1/auth/me").status_code == 401


def test_password_change_expires_cookie_and_invalidates_all_sessions(api_client):
    headers = login(api_client)
    first_cookie = api_client.cookies.get("session_token")
    headers = login(api_client)
    second_cookie = api_client.cookies.get("session_token")
    response = api_client.put("/api/v1/profile/password", headers=headers,
                              json={"current_password": "Password123!", "new_password": "ChangedPassword123!"})
    assert response.status_code == 204
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert api_client.cookies.get("session_token") is None
    for cookie in (first_cookie, second_cookie):
        api_client.cookies.set("session_token", cookie)
        assert api_client.get("/api/v1/auth/me").status_code == 401


def test_non_ascii_ssh_key_has_validation_error():
    with pytest.raises(SSHKeyValidationError):
        validate_and_normalize_ed25519_key("ssh-ed25519 éééé")


@pytest.mark.parametrize("endpoint", ["/exercises/hello-c/start", "/exercises/hello-c/grade", "/environment/stop"])
def test_admin_cannot_mutate_student_environment(api_client, tmp_db, monkeypatch, endpoint):
    with connect_db(tmp_db) as conn:
        update_student_role(conn, "student-a-id", "admin")
    manager = Mock()
    monkeypatch.setattr(environment, "get_runtime_manager", lambda: manager)
    response = api_client.post(f"/api/v1{endpoint}", headers=login(api_client))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert manager.mock_calls == []


def test_failed_ssh_propagation_keeps_persisted_key(api_client, tmp_db, monkeypatch, valid_ed25519_key):
    headers = login(api_client)
    manager = SimpleNamespace(get_student_lock=lambda _: threading.Lock(), update_student_ssh_key=Mock())
    manager.update_student_ssh_key.side_effect = HTTPException(
        503, detail={"error": {"code": "CONTAINER_MANAGER_UNAVAILABLE", "message": "Unavailable"}})
    monkeypatch.setattr(profile, "get_runtime_manager", lambda: manager)
    response = api_client.put("/api/v1/profile/ssh-key", headers=headers, json={"public_key": valid_ed25519_key})
    assert response.status_code == 503
    with connect_db(tmp_db) as conn:
        assert not get_student_by_id(conn, "student-a-id")["ssh_public_key"]


def test_missing_build_report_marks_exercise_unavailable(tmp_db, monkeypatch, courses_path):
    from shared.catalog import parse_and_validate_catalog

    catalog = parse_and_validate_catalog(courses_path)
    manager = SimpleNamespace(get_manager_catalog=lambda: {"available": True, "build_report": {}})
    monkeypatch.setattr(courses, "get_catalog", lambda: catalog)
    monkeypatch.setattr(courses, "get_runtime_manager", lambda: manager)
    exercise = next(iter(catalog.list_courses()[0].exercises))
    detail = courses.get_exercise_detail(exercise.id, ({}, {"id": "student-a-id"}))
    assert detail["available"] is False
    assert isinstance(detail["is_expired"], bool)


@pytest.mark.parametrize("manager_available", [False, True])
def test_catalog_availability_requires_healthy_manager(api_client, monkeypatch, courses_path, manager_available):
    from shared.catalog import parse_and_validate_catalog
    from shared.contracts import ExerciseBuildReport, ManagerCatalogResponse

    catalog = parse_and_validate_catalog(courses_path)
    report = ManagerCatalogResponse(
        catalog_hash=catalog.catalog_hash,
        available=manager_available,
        phase="ready",
        build_report={exercise_id: ExerciseBuildReport(available=True) for exercise_id in catalog.exercises_by_id},
    ).model_dump(mode="json")
    manager = SimpleNamespace(get_manager_catalog=lambda: report)
    monkeypatch.setattr(courses, "get_catalog", lambda: catalog)
    monkeypatch.setattr(courses, "get_runtime_manager", lambda: manager)
    login(api_client)

    response = api_client.get("/api/v1/courses")
    assert response.status_code == 200
    assert all(course["available"] is manager_available for course in response.json()["courses"])

    course = catalog.list_courses()[0]
    response = api_client.get(f"/api/v1/courses/{course.id}")
    assert response.status_code == 200
    assert all(exercise["available"] is manager_available
               for group in response.json()["exercises_by_difficulty"].values() for exercise in group)

    response = api_client.get(f"/api/v1/exercises/{course.exercises[0].id}")
    assert response.status_code == 200
    assert response.json()["available"] is manager_available
