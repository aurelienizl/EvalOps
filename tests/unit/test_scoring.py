"""Unit tests for evaluation scoring rules and completion persistence."""

import json
import pytest

from backend.src.db import (
    connect_db,
    create_initial_evaluation,
    finalize_evaluation,
    get_completed_exercise_ids,
    get_evaluation,
    mark_exercise_completed,
)


@pytest.mark.parametrize("passed, total, expected_pct, expected_success", [
    (0, 3, 0.0, False),
    (1, 3, 33.33, False),
    (2, 3, 66.67, False),
    (3, 3, 100.0, True),
    (0, 1, 0.0, False),
    (1, 1, 100.0, True),
])
def test_scoring_formula(passed, total, expected_pct, expected_success):
    """Verifies percentage rounding and success determination logic."""
    pct = round(100.0 * passed / total, 2)
    success = (passed == total)
    assert pct == expected_pct
    assert success == expected_success


def test_completion_is_permanent(tmp_db):
    """Once an exercise is completed at 100%, subsequent attempts never revoke completion."""
    student_id = "student-a-id"
    exercise_id = "hello-shell"
    eval_id = "eval-first-id"

    with connect_db(tmp_db) as conn:
        # Initially not completed
        assert exercise_id not in get_completed_exercise_ids(conn, student_id)

        # First attempt: create evaluation and mark 100% completed
        create_initial_evaluation(conn, eval_id, student_id, exercise_id, "Hello Shell")
        mark_exercise_completed(conn, student_id, exercise_id, eval_id)
        assert exercise_id in get_completed_exercise_ids(conn, student_id)

        # Second attempt with a lower score must preserve completion
        assert exercise_id in get_completed_exercise_ids(conn, student_id)


def test_finalize_evaluation_persists_score_and_tests(tmp_db):
    """Finalizing an evaluation correctly records score, status, and test details in DB."""
    student_id = "student-a-id"
    eval_id = "eval-test-01"
    tests = [
        {"id": "t1", "name": "Compilation", "passed": True, "message": "OK"},
        {"id": "t2", "name": "Execution", "passed": False, "message": "Failed assertion"},
    ]

    with connect_db(tmp_db) as conn:
        create_initial_evaluation(conn, eval_id, student_id, "hello-shell", "Hello Shell")
        finalize_evaluation(
            conn=conn,
            evaluation_id=eval_id,
            status="completed",
            passed=1,
            total=2,
            percentage=50.0,
            tests_json=json.dumps(tests),
        )

        row = get_evaluation(conn, eval_id)
        assert row["status"] == "completed"
        assert row["passed"] == 1
        assert row["total"] == 2
        assert row["percentage"] == 50.0
        assert json.loads(row["tests_json"]) == tests
