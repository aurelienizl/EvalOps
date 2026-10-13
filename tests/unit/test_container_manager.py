"""Unit tests for the container manager service and docker runtime logic."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fastapi import HTTPException

from container_manager.src.builds import BuildManager
from container_manager.src.docker_runtime import (
    CONTAINER_CPU_LIMIT,
    CONTAINER_MEM_LIMIT,
    CONTAINER_PIDS_LIMIT,
    DockerRuntime,
)
from container_manager.src.services import state as manager_state
from container_manager.src.api.v1.environments import start_student_environment
from container_manager.src.api.v1.evaluations import grade_student_environment
from shared.contracts import ManagerGradeRequest, ManagerStartRequest


def test_resource_quota_specifications():
    """Security constraints: 0.5 CPU, 512MB RAM, and 96 PIDs limits."""
    assert CONTAINER_CPU_LIMIT == int(0.5 * 1e9)
    assert CONTAINER_MEM_LIMIT == "512m"
    assert CONTAINER_PIDS_LIMIT == 96


def test_naming_conventions():
    """Container and volume names strictly follow platform naming conventions."""
    client = Mock()
    runtime = DockerRuntime(
        docker_client=client,
        platform_instance="test-instance",
        ssh_host="localhost",
    )
    assert runtime.get_dev_container_name("student-42") == "devops-test-instance-dev-student-42"
    assert runtime.get_student_volume_name("student-42") == "devops-test-instance-student-student-42"


def test_port_allocation_pool():
    """Ports are allocated sequentially within range and released properly."""
    client = Mock()
    client.containers.list.return_value = []
    runtime = DockerRuntime(
        docker_client=client,
        platform_instance="test-instance",
        ssh_host="localhost",
        ssh_port_min=22000,
        ssh_port_max=22002,
    )

    # Allocate ports
    p1 = runtime.allocate_port("student-1")
    p2 = runtime.allocate_port("student-2")
    p3 = runtime.allocate_port("student-3")

    assert p1 == 22000
    assert p2 == 22001
    assert p3 == 22002

    # Pool exhausted -> raises RuntimeError
    with pytest.raises(RuntimeError, match="SSH_PORTS_EXHAUSTED"):
        runtime.allocate_port("student-4")

    # Release student-2's port -> 22001 becomes available again
    runtime.release_port_for_student("student-2")
    reallocated = runtime.allocate_port("student-4")
    assert reallocated == 22001


def test_student_lock_isolation():
    """Distinct students receive distinct threading locks; identical students share the same lock."""
    client = Mock()
    runtime = DockerRuntime(client, "test-instance", "localhost")

    lock_a = runtime.get_student_lock("student-a")
    lock_b = runtime.get_student_lock("student-b")
    assert lock_a is not lock_b

    # Idempotent call returns identical lock
    assert runtime.get_student_lock("student-a") is lock_a


def test_build_manager_tolerates_partial_failures():
    """If one exercise image fails to build, other exercises still build successfully."""
    client = Mock()
    # First exercise fails on dev build, second succeeds
    client.images.build.side_effect = [
        RuntimeError("syntax error in Dockerfile"),
        (SimpleNamespace(id="dev-second-id"), []),
        (SimpleNamespace(id="eval-second-id"), []),
    ]

    exercises = {
        "bad-ex": SimpleNamespace(
            id="bad-ex",
            dev_context_path=Path("bad/dev"),
            evaluator_context_path=Path("bad/evaluator"),
        ),
        "good-ex": SimpleNamespace(
            id="good-ex",
            dev_context_path=Path("good/dev"),
            evaluator_context_path=Path("good/evaluator"),
        ),
    }

    bm = BuildManager(client, "inst123")
    report = bm.run_all_builds(SimpleNamespace(exercises_by_id=exercises))

    assert bm.is_ready is True
    assert bm.phase == "ready"

    # Bad exercise marked unavailable
    assert report["bad-ex"]["available"] is False
    assert "syntax error" in report["bad-ex"]["error"]

    # Good exercise marked available
    assert report["good-ex"]["available"] is True
    assert report["good-ex"]["dev_image_id"] == "dev-second-id"
    assert report["good-ex"]["evaluator_image_id"] == "eval-second-id"


@pytest.mark.parametrize("operation", ["start", "grade"])
@pytest.mark.parametrize("condition, expected_code, expected_status", [
    ("uninitialized_runtime", "MANAGER_UNAVAILABLE", 503),
    ("preparing_platform", "PLATFORM_PREPARING", 503),
    ("exercise_not_found", "EXERCISE_NOT_FOUND", 404),
    ("image_unavailable", "EXERCISE_UNAVAILABLE", 503),
])
def test_container_manager_endpoint_validation(monkeypatch, operation, condition, expected_code, expected_status):
    """Manager endpoints validate state and parameters before dispatching Docker commands."""
    runtime = Mock()
    builder = SimpleNamespace(is_ready=(condition != "preparing_platform"), report={"ex1": {"available": condition != "image_unavailable", "dev_image_id": "img1", "evaluator_image_id": "img2"}})
    catalog = SimpleNamespace(get_exercise=Mock(return_value=None if condition == "exercise_not_found" else object()))

    monkeypatch.setattr(manager_state, "_docker_runtime", None if condition == "uninitialized_runtime" else runtime)
    monkeypatch.setattr(manager_state, "_build_manager", None if condition == "uninitialized_runtime" else builder)
    monkeypatch.setattr(manager_state, "_catalog", catalog)

    req = ManagerStartRequest(operation_id="op1", exercise_id="ex1", ssh_public_key="ssh-ed25519 test") if operation == "start" else ManagerGradeRequest(operation_id="op1", exercise_id="ex1")
    handler = start_student_environment if operation == "start" else grade_student_environment

    with pytest.raises(HTTPException) as exc:
        handler("student-1", req)

    assert exc.value.status_code == expected_status
    assert exc.value.detail["error"]["code"] == expected_code
    assert not runtime.mock_calls
