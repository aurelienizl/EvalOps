"""Drive the running manager through PostgreSQL, without calling its functions."""

from tests.tools.deployment import ROOT
from tests.tools.database import quote
from tests.tools.users import HELLO, HANG, SLOW_HELLO, SUM
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
    ssh.run("mkdir hello-c")
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


def test_student_home_survives_exercise_changes_grading_and_expiration(deployment, users):
    student, other = users(), users()
    ssh = student.start()
    mounts = deployment.containers(student.id, "development")[0].attrs["Mounts"]
    home_mounts = [mount for mount in mounts if mount["Destination"].startswith("/home/student")]
    assert len(home_mounts) == 1
    assert home_mounts[0]["Destination"] == "/home/student" and home_mounts[0]["RW"]
    assert ssh.run('printf "%s" "$HOME"') == "/home/student"
    assert ssh.run('stat -c "%u:%g:%a" "$HOME"').strip() == "1000:1000:700"
    ssh.run("test -s ~/.bashrc && test -s ~/.profile && test ! -w /etc")
    ssh.run("test ! -e ~/hello-c && mkdir ~/hello-c")
    ssh.write(".vimrc", "set number\n")
    ssh.write(".bash_aliases", "alias study='printf home-ready'\n")
    profile = ssh.run("cat ~/.profile") + "\n# Personal shell settings\n"
    ssh.write(".profile", profile)
    ssh.run("mkdir -p ~/.config/study")
    ssh.write(".config/study/preferences", "personal settings\n")
    ssh.write("hello-c/note.txt", "saved exercise\n")
    assert ssh.run("bash -ic study") == "home-ready"
    ssh.run(
        "vim -N -es -i NONE -u ~/.vimrc "
        "-c 'call writefile([string(&number)], \"/tmp/vim-number\")' -c 'qa!'"
    )
    assert ssh.run("cat /tmp/vim-number").strip() == "1"

    second = other.start()
    second.run("test ! -e ~/.vimrc && test ! -e ~/.config/study/preferences")
    second.write(".vimrc", "set nonumber\n")
    assert ssh.run("cat ~/.vimrc") == "set number\n"
    student.stop()
    ssh = student.start("sum-c")
    ssh.run("test ! -e ~/sum-c && mkdir ~/sum-c")
    assert ssh.run("cat ~/.profile") == profile
    assert ssh.run("cat ~/.vimrc") == "set number\n"
    assert ssh.run("bash -ic study") == "home-ready"
    assert ssh.run("cat ~/hello-c/note.txt") == "saved exercise\n"
    ssh.run("rm ~/hello-c/note.txt")
    ssh.write("hello-c/managed-from-sum.txt", "managed from another exercise\n")
    ssh.write("sum-c/sum.c", SUM)
    evaluation = student.submit("sum-c")
    assert student.report(evaluation)["is_success"]
    snapshot = student.snapshot(evaluation)
    assert snapshot["workspace/sum.c"].decode() == SUM
    assert all(name.startswith("workspace/") for name in snapshot)
    assert not any(".vimrc" in name or ".bash_aliases" in name for name in snapshot)
    assert "workspace/managed-from-sum.txt" not in snapshot

    ssh = student.start()
    ssh.run("test ! -e ~/hello-c/note.txt")
    assert ssh.run("cat ~/hello-c/managed-from-sum.txt") == "managed from another exercise\n"
    assert ssh.run("cat ~/.config/study/preferences") == "personal settings\n"
    deployment.db.execute(
        f"UPDATE environments SET expires_at=now()-interval '1 second' WHERE user_id={quote(student.id)}"
    )
    student.wait_environment("stopped")
    ssh = student.start()
    assert ssh.run("cat ~/.profile") == profile
    assert ssh.run("cat ~/.vimrc") == "set number\n"
    assert ssh.run("bash -ic study") == "home-ready"
    assert second.run("cat ~/.vimrc") == "set nonumber\n"


def test_workspace_configuration_is_only_used_for_grading(deployment, users):
    student, db = users(), deployment.db
    original = db.rows("SELECT workspace_dir FROM exercises WHERE id='hello-c'")[0]["workspace_dir"]
    try:
        db.execute("UPDATE exercises SET workspace_dir='custom-submission' WHERE id='hello-c'")
        ssh = student.start()
        ssh.run("test ! -e ~/hello-c && test ! -e ~/custom-submission")
        report = student.report(student.submit())
        assert report["status"] == "failed" and not report["snapshot_available"]
        ssh = student.start()
        ssh.run("test ! -e ~/custom-submission && mkdir ~/custom-submission")
        ssh.write("custom-submission/main.c", HELLO)
        evaluation = student.submit()
        assert student.report(evaluation)["is_success"]
        assert student.snapshot(evaluation)["workspace/main.c"] == HELLO.encode()
    finally:
        db.execute(f"UPDATE exercises SET workspace_dir={quote(original)} WHERE id='hello-c'")


def test_student_can_repair_an_invalid_exercise_tree(users):
    student = users()
    ssh = student.start()
    ssh.run("ln -s /etc/training ~/sum-c")
    student.stop()
    student.start("sum-c")
    report = student.report(student.submit("sum-c"))
    assert report["status"] == "failed" and report["error_code"] == "evaluation_failed"
    assert not report["snapshot_available"]
    ssh = student.start("sum-c")
    ssh.run("rm ~/sum-c && mkdir ~/sum-c")
    ssh.write("sum-c/sum.c", SUM)
    assert student.report(student.submit("sum-c"))["is_success"]


def test_grading_stops_development_and_handles_timeout(deployment, users):
    student, db = users(), deployment.db
    env = db.start(student.id)
    student.ssh(env).run("mkdir hello-c")
    student.ssh(env).write("hello-c/main.c", SLOW_HELLO)
    evaluation_id = db.grade(student.id)
    evaluators = eventually(
        lambda: deployment.containers(student.id, "evaluator"), description="evaluator start"
    )
    assert all(mount["Destination"] != "/home/student" for mount in evaluators[0].attrs["Mounts"])
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
    student.ssh(env).run("mkdir hello-c")
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
