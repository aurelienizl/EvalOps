"""Teacher lookup, progress and report permissions against the real database/API."""

from uuid import uuid4
import pytest
from tests.tools.database import quote


@pytest.fixture
def admin_class(users, deployment):
    teacher, active, inactive = users(role="admin"), users(), users(ssh_key=False)
    prefix = "class-" + uuid4().hex[:8]
    for student, label in ((active, "alex"), (inactive, "sam")):
        student.email = f"{prefix}-{label}@example.test"
        deployment.db.execute(
            f"UPDATE users SET email={quote(student.email)} WHERE id={quote(student.id)}"
        )
    records = {}
    for index, (result, status, success, exercise) in enumerate(
        (
            ("validated", "completed", True, "hello-c"),
            ("timeout", "timeout", False, "sum-c"),
            ("error", "failed", False, "sum-c"),
            ("grading", "running", False, "sum-c"),
            ("unsuccessful", "completed", False, "hello-c"),
        )
    ):
        evaluation = str(uuid4())
        records[result] = evaluation
        deployment.db.execute(f"""INSERT INTO evaluations
            (id,user_id,exercise_id,status,is_success,passed_tests,total_tests,created_at,finished_at)
            VALUES({quote(evaluation)},{quote(active.id)},{quote(exercise)},{quote(status)},
            {str(success).lower()},{3 if success else 0},3,now()-interval '{10 - index} minutes',
            {"NULL" if status == "running" else "now()"});""")
    deployment.db.execute(f"""INSERT INTO user_completed_exercises
        (user_id,exercise_id,successful_evaluation_id)
        VALUES({quote(active.id)},'hello-c',{quote(records["validated"])});""")
    diagnostic = '<img src=x onerror="window.__teacherXss=true">'
    deployment.db.execute(f"""INSERT INTO evaluation_tests(evaluation_id,name,status,stderr_diff)
        VALUES({quote(records["unsuccessful"])},{quote(diagnostic)},'failed','Expected Hello C');""")
    try:
        yield dict(
            teacher=teacher,
            active=active,
            inactive=inactive,
            prefix=prefix,
            records=records,
            diagnostic=diagnostic,
        )
    finally:
        deployment.db.execute(f"DELETE FROM evaluations WHERE user_id={quote(active.id)}")


def test_teacher_student_lookup_includes_students_without_submissions(admin_class):
    teacher, active, inactive = (admin_class[key] for key in ("teacher", "active", "inactive"))
    result = teacher.api.get(
        "/admin/students",
        params={
            "search": admin_class["prefix"].upper(),
            "course_id": "examples",
        },
    ).json()
    assert result["total"] == 2
    assert result["total_exercises"] == 8
    rows = {row["id"]: row for row in result["items"]}
    assert rows[inactive.id]["submissions"] == 0
    assert rows[inactive.id]["last_submission_at"] is None
    assert rows[active.id]["submissions"] == 5
    assert rows[active.id]["attempted_exercises"] == 2
    assert rows[active.id]["validated_exercises"] == 1
    assert rows[active.id]["latest_status"] == "completed"
    assert rows[active.id]["latest_is_success"] is False
    assert rows[active.id]["last_submission_id"] == admin_class["records"]["unsuccessful"]
    filtered = teacher.api.get(
        "/admin/students",
        params={
            "user_id": active.id,
            "course_id": "does-not-exist",
        },
    ).json()
    assert filtered["total_exercises"] == 0
    assert filtered["items"][0]["submissions"] == 0
    assert filtered["items"][0]["validated_exercises"] == 0
    assert teacher.api.get("/admin/students", params={"search": teacher.email}).json()["total"] == 0
    page = teacher.api.get(
        "/admin/students",
        params={
            "search": admin_class["prefix"],
            "limit": 1,
            "offset": 1,
        },
    ).json()
    assert page["total"] == 2 and len(page["items"]) == 1
    active.api.get("/admin/students", expected=403)
    teacher.api.get("/admin/students?user_id=invalid", expected=422)
    teacher.api.get("/admin/students?limit=101", expected=422)
    assert teacher.api.get("/admin/stats").json()["students"] >= 2


def test_teacher_submission_filters_and_full_reports(admin_class):
    teacher, active, inactive = (admin_class[key] for key in ("teacher", "active", "inactive"))
    for result, evaluation in admin_class["records"].items():
        rows = teacher.api.get(
            "/admin/evaluations",
            params={
                "user_id": active.id,
                "course_id": "examples",
                "outcome": result,
                "search": active.email.upper(),
            },
        ).json()
        assert rows["total"] == 1
        assert rows["items"][0]["id"] == evaluation
        assert rows["items"][0]["exercise_name"]
        assert rows["items"][0]["total_tests"] == 3
    assert (
        teacher.api.get(
            "/admin/evaluations",
            params={
                "user_id": active.id,
                "course_id": "does-not-exist",
            },
        ).json()["total"]
        == 0
    )
    teacher.api.get("/admin/evaluations?outcome=invalid", expected=422)
    evaluation = admin_class["records"]["unsuccessful"]
    report = teacher.api.get(f"/admin/evaluations/{evaluation}").json()
    assert report["email"] == active.email
    assert report["tests"][0]["name"] == admin_class["diagnostic"]
    assert report["tests"][0]["stderr_diff"] == "Expected Hello C"
    assert "snapshot_archive_path" not in report
    active.api.get(f"/admin/evaluations/{evaluation}", expected=403)
    inactive.api.get(f"/evaluations/{evaluation}", expected=404)
    teacher.api.get(f"/evaluations/{evaluation}", expected=404)
    teacher.api.get(f"/admin/evaluations/{uuid4()}", expected=404)
