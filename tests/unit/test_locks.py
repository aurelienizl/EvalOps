"""Unit tests for student concurrency locks and runtime state management."""

import pytest
from types import SimpleNamespace
from unittest.mock import Mock

from backend.src.db import (
    clear_student_runtime,
    connect_db,
    get_student_runtime,
    set_student_runtime,
)
from backend.src.runtime import RuntimeManager
from shared.catalog import parse_and_validate_catalog


def test_independent_student_locks(courses_path):
    """Student locks are isolated: acquiring lock for Student A does not block Student B."""
    catalog = parse_and_validate_catalog(courses_path)
    rm = RuntimeManager(catalog)

    student_a = "student-a-id"
    student_b = "student-b-id"

    lock_a = rm.get_student_lock(student_a)
    lock_b = rm.get_student_lock(student_b)

    # Acquire lock A
    assert lock_a.acquire(blocking=False) is True
    assert rm.is_student_locked(student_a) is True

    # Lock A cannot be acquired concurrently
    assert lock_a.acquire(blocking=False) is False

    # Student B remains completely unlocked
    assert rm.is_student_locked(student_b) is False
    assert lock_b.acquire(blocking=False) is True
    assert rm.is_student_locked(student_b) is True

    # Release both
    lock_a.release()
    assert rm.is_student_locked(student_a) is False

    lock_b.release()
    assert rm.is_student_locked(student_b) is False


def test_persistent_student_runtime(tmp_db):
    """Database runtime state tracks active operations and clears properly."""
    student_id = "student-a-id"

    with connect_db(tmp_db) as conn:
        assert get_student_runtime(conn, student_id) is None

        set_student_runtime(
            conn,
            student_id=student_id,
            operation_id="op-grade-123",
            operation_type="grade",
            exercise_id="hello-shell",
            phase="grading",
        )

        rt = get_student_runtime(conn, student_id)
        assert rt is not None
        assert rt["operation_id"] == "op-grade-123"
        assert rt["phase"] == "grading"

        clear_student_runtime(conn, student_id)
        assert get_student_runtime(conn, student_id) is None


@pytest.mark.parametrize("operation", ["start", "stop", "grade"])
def test_transport_failure_clears_runtime_and_unlocks(courses_path, tmp_db, operation):
    """When HTTP transport to container manager fails, operation runtime and lock are cleaned up."""
    catalog = parse_and_validate_catalog(courses_path)
    rm = RuntimeManager(catalog)
    rm.container_client.http_client.close()
    rm.container_client.http_client = Mock()
    rm.container_client.http_client.post.side_effect = RuntimeError("Manager offline")

    student_id = "student-a-id"
    args = {"start": ("hello-c", "ssh-ed25519 AAAAC3..."), "stop": (), "grade": ("hello-c",)}[operation]

    with pytest.raises(RuntimeError, match="Manager offline"):
        getattr(rm, f"{operation}_environment")(student_id, *args)

    # Must not remain locked or lingering in database
    assert not rm.is_student_locked(student_id)
    with connect_db(tmp_db) as conn:
        assert get_student_runtime(conn, student_id) is None
