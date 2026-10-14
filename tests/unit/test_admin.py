"""Unit tests for role-based permissions and generic admin query interfaces."""

import pytest
from fastapi.testclient import TestClient

from backend.src.app import app
from backend.src.core.security import hash_password
from backend.src.db import (
    connect_db,
    create_initial_evaluation,
    create_student,
    finalize_evaluation,
    set_student_runtime,
)


@pytest.fixture
def auth_admin(tmp_db, make_student_client):
    """Creates and logs in an admin user."""
    with connect_db(tmp_db) as conn:
        create_student(
            conn,
            student_id="admin-user-id",
            email="admin@ecole.fr",
            password_hash=hash_password("AdminPass123!"),
            role="admin",
        )
    return make_student_client("admin@ecole.fr", password="AdminPass123!")


def test_student_forbidden_from_admin_endpoints(auth_alice):
    """Regular student cannot access admin endpoints (returns 403 FORBIDDEN)."""
    # GET /api/v1/admin/users
    res = auth_alice["client"].get("/api/v1/admin/users")
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FORBIDDEN"

    # GET /api/v1/admin/stats
    res = auth_alice["client"].get("/api/v1/admin/stats")
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FORBIDDEN"

    # POST /api/v1/admin/users
    res = auth_alice["client"].post(
        "/api/v1/admin/users",
        json={"email": "newbie@ecole.fr", "password": "Password123!", "role": "student"},
        headers=auth_alice["headers"],
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FORBIDDEN"


def test_admin_list_and_search_users(auth_admin):
    """Admin can query users with pagination, role filtering, and email substring search."""
    # List all users
    res = auth_admin["client"].get("/api/v1/admin/users")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert data["total"] >= 3  # alice, bob, admin
    assert any(u["email"] == "alice@ecole.fr" for u in data["items"])

    # Search by email
    res_search = auth_admin["client"].get("/api/v1/admin/users?search=alice")
    assert res_search.status_code == 200
    search_data = res_search.json()
    assert len(search_data["items"]) == 1
    assert search_data["items"][0]["email"] == "alice@ecole.fr"

    # Filter by role
    res_role = auth_admin["client"].get("/api/v1/admin/users?role=admin")
    assert res_role.status_code == 200
    role_data = res_role.json()
    assert all(u["role"] == "admin" for u in role_data["items"])
    assert any(u["email"] == "admin@ecole.fr" for u in role_data["items"])


def test_admin_create_user_and_update_role(auth_admin):
    """Admin can create a new student or admin, and change roles."""
    # 1. Create a new user
    res_create = auth_admin["client"].post(
        "/api/v1/admin/users",
        json={"email": "charlotte@ecole.fr", "password": "CharlottePass123!", "role": "student"},
        headers=auth_admin["headers"],
    )
    assert res_create.status_code == 201
    created = res_create.json()
    assert created["email"] == "charlotte@ecole.fr"
    assert created["role"] == "student"
    new_user_id = created["id"]

    # 2. Promote to admin
    res_role = auth_admin["client"].put(
        f"/api/v1/admin/users/{new_user_id}/role",
        json={"role": "admin"},
        headers=auth_admin["headers"],
    )
    assert res_role.status_code == 200
    assert res_role.json()["role"] == "admin"

    # 3. Verify in user listing
    res_list = auth_admin["client"].get("/api/v1/admin/users?search=charlotte")
    assert res_list.json()["items"][0]["role"] == "admin"


def test_admin_evaluations_and_platform_stats(auth_admin, tmp_db):
    """Admin can query platform-wide evaluations and aggregated statistics."""
    # Seed an evaluation record
    with connect_db(tmp_db) as conn:
        create_initial_evaluation(
            conn,
            evaluation_id="eval-test-123",
            student_id="student-a-id",
            exercise_id="hello-c",
            exercise_name="Hello C",
        )
        finalize_evaluation(
            conn,
            evaluation_id="eval-test-123",
            status="completed",
            passed=2,
            total=2,
            percentage=100.0,
            tests_json='[{"name": "test_output", "status": "passed"}]',
        )

    # Stats
    res_stats = auth_admin["client"].get("/api/v1/admin/stats")
    assert res_stats.status_code == 200
    stats = res_stats.json()
    assert "total_users" in stats
    assert stats["total_evaluations"] >= 1
    assert stats["passed_evaluations"] >= 1

    # Query evaluations (reproducing GET /api/v1/admin/evaluations?limit=15&offset=0)
    res_evals = auth_admin["client"].get("/api/v1/admin/evaluations?limit=15&offset=0")
    assert res_evals.status_code == 200
    eval_data = res_evals.json()
    assert "items" in eval_data
    assert eval_data["total"] >= 1
    item = next(it for it in eval_data["items"] if it["id"] == "eval-test-123")
    assert item["student_id"] == "student-a-id"
    assert item["exercise_id"] == "hello-c"
    assert item["status"] == "completed"
    assert item["passed"] == 2
    assert item["total"] == 2
    assert item["percentage"] == 100.0
    assert len(item["tests"]) == 1
    assert item["tests"][0]["name"] == "test_output"

    # Query with filters
    res_filtered = auth_admin["client"].get("/api/v1/admin/evaluations?student_id=student-a-id&status=completed")
    assert res_filtered.status_code == 200
    assert any(it["id"] == "eval-test-123" for it in res_filtered.json()["items"])

    res_empty = auth_admin["client"].get("/api/v1/admin/evaluations?exercise_id=unknown-exercise")
    assert res_empty.status_code == 200
    assert len(res_empty.json()["items"]) == 0


def test_admin_environments_and_force_unlock(auth_admin, tmp_db):
    """Admin can inspect active environments and force unlock a locked student."""
    # Simulate a stuck operation for Alice
    with connect_db(tmp_db) as conn:
        set_student_runtime(conn, "student-a-id", "op-stuck-123", "grade", "hello-c", "grading")

    # Admin inspects environments
    res_env = auth_admin["client"].get("/api/v1/admin/environments")
    assert res_env.status_code == 200
    active = res_env.json()["active_environments"]
    assert any(op["student_id"] == "student-a-id" for op in active)

    # Force unlock Alice
    res_unlock = auth_admin["client"].post(
        "/api/v1/admin/environments/student-a-id/unlock",
        headers=auth_admin["headers"],
    )
    assert res_unlock.status_code == 200
    assert res_unlock.json()["status"] == "unlocked"

    # Verify runtime is cleared
    res_env_after = auth_admin["client"].get("/api/v1/admin/environments")
    active_after = res_env_after.json()["active_environments"]
    assert not any(op["student_id"] == "student-a-id" for op in active_after)
