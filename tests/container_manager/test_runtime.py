"""Drive the running manager through PostgreSQL, without calling its functions."""

from tests.tools.deployment import ROOT
from tests.tools.database import quote
from tests.tools.users import HELLO, HANG, SLOW_HELLO
from tests.tools.wait import eventually


def test_catalog_readiness_and_single_instance(deployment):
    manager = deployment.service("container_manager")
    assert manager.attrs["State"]["Health"]["Status"] == "healthy"
    expected = len(list((ROOT / "courses").glob("*/exercises/*/exercise.yaml")))
    assert len(deployment.db.rows("SELECT id FROM exercises")) == expected
    second = deployment.compose(
        "run", "--rm", "--no-deps", "container_manager", check=False, timeout=30
    )
    assert second.returncode != 0
    assert "Another Container Manager is already connected" in second.stderr
    manager.reload()
    assert manager.status == "running"


def test_database_commands_ssh_persistence_and_crash_recovery(deployment, users):
    student, db = users(), deployment.db
    env = db.start(student.id, notify=False)  # Polling recovers a request without NOTIFY.
    ssh = student.ssh(env)
    assert "1000" in ssh.run("test -t 0 && id -u", terminal=True)
    ssh.write("hello-c/note.txt", "saved work\n")
    first_id = env["container_id"]
    stopped = db.stop(student.id)
    assert stopped["container_id"] is None and stopped["ssh_port"] is None
    assert not deployment.containers(student.id)
    env = db.start(student.id)
    assert env["container_id"] != first_id
    assert student.ssh(env).run("cat hello-c/note.txt") == "saved work\n"
    deployment.restart_manager()
    assert db.environment(student.id)["container_id"] == env["container_id"]
    deployment.docker.containers.get(env["container_id"]).kill()
    db.wait_environment(student.id, "stopped")
    assert not deployment.containers(student.id)


def test_grading_stops_development_and_handles_timeout(deployment, users):
    student, db = users(), deployment.db
    env = db.start(student.id)
    student.ssh(env).write("hello-c/main.c", SLOW_HELLO)
    evaluation_id = db.grade(student.id)
    eventually(
        lambda: deployment.containers(student.id, "evaluator"), description="evaluator start"
    )
    assert not deployment.containers(student.id, "development")
    assert db.environment(student.id)["status"] == "grading"
    report = db.wait_report(evaluation_id)
    assert report["status"] == "completed" and report["is_success"]
    assert report["snapshot_archive_path"]
    assert db.rows(f"SELECT name FROM evaluation_tests WHERE evaluation_id={quote(evaluation_id)}")
    db.wait_environment(student.id, "stopped")
    assert not deployment.containers(student.id)
    timeout = db.rows("SELECT grade_timeout_seconds FROM exercises WHERE id='hello-c'")[0][
        "grade_timeout_seconds"
    ]
    try:
        db.execute("UPDATE exercises SET grade_timeout_seconds=1 WHERE id='hello-c';")
        env = db.start(student.id)
        student.ssh(env).write("hello-c/main.c", HANG)
        report = db.wait_report(db.grade(student.id))
        assert report["status"] == "timeout" and report["error_code"] == "grade_timeout"
        db.wait_environment(student.id, "stopped")
        assert not deployment.containers(student.id)
    finally:
        db.execute(f"UPDATE exercises SET grade_timeout_seconds={timeout} WHERE id='hello-c';")


def test_restart_during_grading_cleans_up_and_allows_retry(deployment, users):
    student, db = users(), deployment.db
    env = db.start(student.id)
    student.ssh(env).write("hello-c/main.c", HANG)
    evaluation_id = db.grade(student.id)
    eventually(
        lambda: deployment.containers(student.id, "evaluator"), description="evaluator start"
    )
    deployment.restart_manager()
    report = db.wait_report(evaluation_id)
    assert report["status"] == "failed" and report["error_code"] == "worker_interrupted"
    db.wait_environment(student.id, "stopped")
    assert not deployment.containers(student.id)
    env = db.start(student.id)
    student.ssh(env).write("hello-c/main.c", HELLO)
    assert db.wait_report(db.grade(student.id))["is_success"]
