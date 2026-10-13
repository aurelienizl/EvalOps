"""Backend/manager boundary checks without Docker or a running manager."""

import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import HTTPException

from backend.src.db import (
    connect_db,
    create_initial_evaluation,
    get_evaluation,
    get_student_runtime,
    set_student_runtime,
)
from backend.src.runtime import RuntimeManager
from backend.src.services.container_client import ContainerManagerClient
from shared.contracts import RuntimeState

STUDENT = "student-a-id"
EXERCISE = "example"


@pytest.fixture
def runtime(tmp_db):
    exercise = SimpleNamespace(
        id=EXERCISE,
        name="Example",
        points=5,
        course_id="course",
        max_evaluations=3,
        evaluation_window_minutes=60,
        grade_timeout_seconds=120,
    )
    catalog = SimpleNamespace(
        get_exercise=Mock(return_value=exercise), get_course=Mock(return_value=None)
    )
    manager = RuntimeManager(catalog)
    yield manager
    manager.close()


def serve(runtime, handler):
    runtime.container_client.http_client.close()
    runtime.container_client.http_client = httpx.Client(
        base_url="http://manager", transport=httpx.MockTransport(handler)
    )


def operation(
    status="running", operation_id="pending", operation_type="grade", result=None
):
    return {
        "operation_id": operation_id,
        "type": operation_type,
        "status": status,
        "started_at": 1700000000.0,
        "exercise_id": EXERCISE,
        "result": result,
    }


def seed_pending(operation_type="grade"):
    with connect_db() as conn:
        set_student_runtime(
            conn, STUDENT, "pending", operation_type, EXERCISE, "grading"
        )
        if operation_type == "grade":
            create_initial_evaluation(conn, "pending", STUDENT, EXERCISE, "Example", 5)


def grade_result(operation_id="pending", **overrides):
    return {
        "operation_id": operation_id,
        "exercise_id": EXERCISE,
        "status": "completed",
        "tests": [{"id": "one", "passed": True}],
        **overrides,
    }


def test_start_provisions_key_and_returns_validated_environment(runtime):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "state": "running",
                "exercise": {"id": EXERCISE, "name": "Example"},
                "ssh": {"host": "localhost", "port": 22000},
            },
        )

    serve(runtime, handler)
    environment = runtime.start_environment(STUDENT, EXERCISE, "ssh-ed25519 key")
    assert seen[0]["ssh_public_key"] == "ssh-ed25519 key"
    assert environment["locked"] is False
    assert environment["ssh"]["port"] == 22000
    assert not runtime.is_student_locked(STUDENT)
    with connect_db() as conn:
        assert get_student_runtime(conn, STUDENT) is None


def test_manager_error_contract_preserved(runtime):
    serve(
        runtime,
        lambda request: httpx.Response(
            503, json={"error": {"code": "UNAVAILABLE", "message": "Unavailable"}}
        ),
    )
    with pytest.raises(HTTPException) as failure:
        runtime.stop_environment(STUDENT)
    assert failure.value.status_code == 503
    assert failure.value.detail["error"]["code"] == "UNAVAILABLE"
    assert failure.value.detail["error"]["operation_id"]


@pytest.mark.parametrize(
    "response, status, code",
    [
        (
            httpx.Response(502, text="<html>Proxy unavailable</html>"),
            502,
            "CONTAINER_MANAGER_ERROR",
        ),
        (httpx.Response(200, text="invalid json"), 502, "INVALID_MANAGER_RESPONSE"),
        (httpx.Response(200, json=[]), 502, "INVALID_MANAGER_RESPONSE"),
        (
            httpx.Response(200, json={"state": "running"}),
            502,
            "INVALID_MANAGER_RESPONSE",
        ),
    ],
)
def test_invalid_manager_response_is_a_gateway_error(runtime, response, status, code):
    serve(runtime, lambda request: response)
    with pytest.raises(HTTPException) as failure:
        runtime.stop_environment(STUDENT)
    assert failure.value.status_code == status
    assert failure.value.detail["error"]["code"] == code
    assert not runtime.is_student_locked(STUDENT)


@pytest.mark.parametrize(
    "error_type", [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout]
)
def test_grade_connection_failure_finalizes_trace_and_unlocks(runtime, error_type):
    def handler(request):
        raise error_type("offline", request=request)

    serve(runtime, handler)
    with pytest.raises(HTTPException) as failure:
        runtime.grade_environment(STUDENT, EXERCISE)
    assert failure.value.status_code == 502
    with connect_db() as conn:
        evaluation = conn.execute("SELECT * FROM evaluations").fetchone()
        assert evaluation["status"] == "error"
        assert evaluation["error_code"] == "CONTAINER_MANAGER_UNAVAILABLE"
        assert get_student_runtime(conn, STUDENT) is None
    assert not runtime.is_student_locked(STUDENT)


def test_successful_grade_computes_score_from_tests(runtime):
    def handler(request):
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            json=grade_result(
                payload["operation_id"],
                tests=[{"id": "one", "passed": True}, {"id": "two", "passed": False}],
            ),
        )

    serve(runtime, handler)
    result = runtime.grade_environment(STUDENT, EXERCISE)
    assert result["evaluation"]["passed"] == 1
    assert result["evaluation"]["total"] == 2
    assert result["evaluation"]["percentage"] == 50.0
    assert result["evaluation"]["success"] is False
    with connect_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM student_exercises").fetchone()[0] == 0
        assert get_student_runtime(conn, STUDENT) is None


def test_grade_result_stays_recoverable_if_database_write_fails(runtime, monkeypatch):
    captured = {}

    def handler(request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=grade_result(captured["operation_id"]))

    serve(runtime, handler)
    save_evaluation = runtime._save_evaluation
    monkeypatch.setattr(
        runtime, "_save_evaluation", Mock(side_effect=sqlite3.OperationalError("busy"))
    )
    with pytest.raises(sqlite3.OperationalError, match="busy"):
        runtime.grade_environment(STUDENT, EXERCISE)
    with connect_db() as conn:
        assert get_student_runtime(conn, STUDENT) is not None
        assert get_evaluation(conn, captured["operation_id"])["status"] == "running"
    assert not runtime.is_student_locked(STUDENT)

    monkeypatch.setattr(runtime, "_save_evaluation", save_evaluation)
    result = grade_result(captured["operation_id"])
    serve(
        runtime,
        lambda request: httpx.Response(
            200,
            json={
                "state": "stopped",
                "active_operation": operation(
                    "completed", captured["operation_id"], result=result
                ),
            },
        ),
    )
    assert runtime.get_environment(STUDENT).locked is False
    with connect_db() as conn:
        assert get_evaluation(conn, captured["operation_id"])["status"] == "completed"


@pytest.mark.parametrize(
    "overrides",
    [
        {"operation_id": "other"},
        {"exercise_id": "other"},
        {"status": "unexpected"},
        {"tests": [{"id": "same", "passed": True}, {"id": "same", "passed": False}]},
    ],
)
def test_bad_grading_result_never_records_success(runtime, overrides):
    def handler(request):
        payload = json.loads(request.content)
        return httpx.Response(
            200, json={**grade_result(payload["operation_id"]), **overrides}
        )

    serve(runtime, handler)
    with pytest.raises(HTTPException) as failure:
        runtime.grade_environment(STUDENT, EXERCISE)
    assert failure.value.detail["error"]["code"] == "INVALID_MANAGER_RESPONSE"
    with connect_db() as conn:
        assert (
            conn.execute("SELECT status FROM evaluations").fetchone()["status"]
            == "error"
        )
        assert conn.execute("SELECT COUNT(*) FROM student_exercises").fetchone()[0] == 0


@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.WriteTimeout])
def test_grading_timeout_keeps_pending_until_live_result_can_be_recovered(
    runtime, error_type
):
    captured = {}

    def timeout(request):
        captured.update(json.loads(request.content))
        raise error_type("waiting", request=request)

    serve(runtime, timeout)
    with pytest.raises(HTTPException) as failure:
        runtime.grade_environment(STUDENT, EXERCISE)
    assert failure.value.status_code == 504
    with connect_db() as conn:
        assert (
            get_student_runtime(conn, STUDENT)["operation_id"]
            == captured["operation_id"]
        )
        assert get_evaluation(conn, captured["operation_id"])["status"] == "running"
    assert not runtime.is_student_locked(STUDENT)

    result = grade_result(captured["operation_id"])
    serve(
        runtime,
        lambda request: httpx.Response(
            200,
            json={
                "state": "stopped",
                "active_operation": operation(
                    "completed", captured["operation_id"], result=result
                ),
            },
        ),
    )
    environment = runtime.get_environment(STUDENT)
    assert environment.state == RuntimeState.STOPPED
    assert environment.locked is False
    assert environment.operation is None
    with connect_db() as conn:
        assert get_student_runtime(conn, STUDENT) is None
        assert get_evaluation(conn, captured["operation_id"])["percentage"] == 100.0
        assert conn.execute("SELECT COUNT(*) FROM student_exercises").fetchone()[0] == 1


@pytest.mark.parametrize("active", [None, operation("failed")])
def test_stale_grading_trace_is_interrupted(runtime, active):
    seed_pending()
    serve(
        runtime,
        lambda request: httpx.Response(
            200, json={"state": "stopped", "active_operation": active}
        ),
    )
    assert runtime.get_environment(STUDENT).locked is False
    with connect_db() as conn:
        assert get_evaluation(conn, "pending")["status"] == "interrupted"
        assert get_student_runtime(conn, STUDENT) is None


def test_conflict_cannot_delete_existing_operation(runtime):
    seed_pending()
    serve(
        runtime,
        lambda request: httpx.Response(
            200, json={"state": "stopped", "active_operation": operation()}
        ),
    )
    with pytest.raises(HTTPException) as failure:
        runtime.stop_environment(STUDENT)
    assert failure.value.status_code == 409
    with connect_db() as conn:
        assert get_student_runtime(conn, STUDENT)["operation_id"] == "pending"
        assert get_evaluation(conn, "pending")["status"] == "running"
    assert not runtime.is_student_locked(STUDENT)


def test_poll_during_local_request_does_not_reconcile_its_trace(runtime):
    seed_pending()
    serve(
        runtime,
        lambda request: httpx.Response(
            200,
            json={
                "state": "stopped",
                "active_operation": operation("completed", result=grade_result()),
            },
        ),
    )
    lock = runtime.get_student_lock(STUDENT)
    with lock:
        assert runtime.get_environment(STUDENT).locked is True
        with connect_db() as conn:
            assert get_evaluation(conn, "pending")["status"] == "running"
            assert get_student_runtime(conn, STUDENT) is not None


def test_manager_only_operation_is_visible_as_locked(runtime):
    serve(
        runtime,
        lambda request: httpx.Response(
            200, json={"state": "stopped", "active_operation": operation()}
        ),
    )
    environment = runtime.get_environment(STUDENT)
    assert environment.state == RuntimeState.GRADING
    assert environment.locked is True
    assert environment.operation.id == "pending"


@pytest.mark.parametrize(
    "body",
    [{"state": "invalid"}, {"state": "running", "ssh": {"host": "host", "port": 0}}],
)
def test_invalid_environment_reports_unknown(runtime, body):
    serve(runtime, lambda request: httpx.Response(200, json=body))
    assert runtime.get_environment(STUDENT).state == RuntimeState.UNKNOWN


def test_lock_releases_if_cleanup_fails(runtime, monkeypatch):
    serve(runtime, lambda request: httpx.Response(200, json={"state": "stopped"}))
    monkeypatch.setattr(
        runtime,
        "_clear_runtime",
        Mock(side_effect=RuntimeError("database unavailable")),
    )
    with pytest.raises(RuntimeError, match="database unavailable"):
        runtime.stop_environment(STUDENT)
    assert not runtime.is_student_locked(STUDENT)


@pytest.mark.parametrize("status", ["running", "unavailable"])
def test_admin_unlock_preserves_operation_when_not_safe(runtime, status):
    seed_pending()
    serve(
        runtime,
        lambda request: (
            httpx.Response(503)
            if status == "unavailable"
            else httpx.Response(
                200, json={"state": "stopped", "active_operation": operation()}
            )
        ),
    )
    with pytest.raises(HTTPException) as failure:
        runtime.unlock_student(STUDENT)
    assert failure.value.status_code == (503 if status == "unavailable" else 409)
    with connect_db() as conn:
        assert get_student_runtime(conn, STUDENT) is not None
    assert not runtime.is_student_locked(STUDENT)


def test_ssh_update_failure_is_reported(runtime):
    serve(
        runtime,
        lambda request: httpx.Response(
            500, json={"error": {"code": "VOLUME_UPDATE_FAILED", "message": "Failed"}}
        ),
    )
    with pytest.raises(HTTPException) as failure:
        runtime.update_student_ssh_key(STUDENT, "ssh-ed25519 key")
    assert failure.value.detail["error"]["code"] == "VOLUME_UPDATE_FAILED"


def test_snapshot_bytes_and_not_found_mapping(runtime):
    serve(runtime, lambda request: httpx.Response(200, content=b"archive"))
    assert runtime.get_evaluation_snapshot(STUDENT, "evaluation") == b"archive"
    serve(runtime, lambda request: httpx.Response(404, text="missing"))
    with pytest.raises(HTTPException) as failure:
        runtime.get_evaluation_snapshot(STUDENT, "evaluation")
    assert failure.value.detail["error"]["code"] == "SNAPSHOT_NOT_FOUND"


def test_close_releases_http_pool(runtime):
    client = runtime.container_client.http_client
    runtime.close()
    assert client.is_closed


@pytest.mark.parametrize(
    "endpoint, arguments, read_timeout",
    [
        ("get_health", (), 5.0),
        ("get_catalog", (), 10.0),
        ("get_student_environment", (STUDENT,), 10.0),
        (
            "start_student_environment",
            (STUDENT, "operation", EXERCISE, "ssh-ed25519 key"),
            90.0,
        ),
        ("stop_student_environment", (STUDENT, "operation"), 45.0),
        ("grade_student_environment", (STUDENT, "operation", EXERCISE, 240.0), 240.0),
        ("update_ssh_key", (STUDENT, "ssh-ed25519 key"), 15.0),
        ("get_snapshot", (STUDENT, "evaluation"), 30.0),
    ],
)
def test_endpoint_read_budget_preserves_connection_and_pool_limits(
    endpoint, arguments, read_timeout
):
    observed = []

    def handler(request):
        observed.append(request.extensions["timeout"])
        return httpx.Response(
            200,
            json={
                "state": "stopped",
                "catalog_hash": "hash",
                "available": True,
                "phase": "ready",
                "build_report": {},
            },
        )

    client = ContainerManagerClient("http://manager")
    client.http_client.close()
    client.http_client = httpx.Client(
        base_url="http://manager", transport=httpx.MockTransport(handler)
    )
    try:
        getattr(client, endpoint)(*arguments)
    finally:
        client.close()
    assert observed == [
        {"connect": 5.0, "read": read_timeout, "write": 10.0, "pool": 10.0}
    ]


def test_custom_client_connection_limits_are_preserved():
    observed = []
    client = ContainerManagerClient(
        "http://manager", timeout=httpx.Timeout(360.0, connect=2.0, write=3.0, pool=4.0)
    )
    client.http_client.close()
    client.http_client = httpx.Client(
        base_url="http://manager",
        transport=httpx.MockTransport(
            lambda request: (
                observed.append(request.extensions["timeout"])
                or httpx.Response(200, json={"state": "stopped"})
            )
        ),
    )
    try:
        client.stop_student_environment(STUDENT, "operation")
    finally:
        client.close()
    assert observed == [{"connect": 2.0, "read": 45.0, "write": 3.0, "pool": 4.0}]
