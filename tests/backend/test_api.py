"""Real HTTP requests with the container manager running."""

from concurrent.futures import ThreadPoolExecutor
from tests.tools.api import Api
from tests.tools.database import quote
from tests.tools.users import HELLO, PASSWORD, SLOW_HELLO


def test_authentication_roles_and_password_change(deployment, users):
    student = users(ssh_key=False)
    other_session = Api(deployment.url)
    try:
        other_session.get("/auth/me", expected=401)
        other_session.post(
            "/auth/login", json={"email": student.email, "password": "wrong"}, expected=401
        )
        response = other_session.login(student.email, PASSWORD)
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=strict" in response.headers["set-cookie"]
        student.api.get("/admin/stats", expected=403)
        student.api.put(
            "/profile/password",
            json={"current_password": "wrong", "new_password": PASSWORD},
            expected=403,
        )
        new_password = PASSWORD + "-changed"
        student.api.put(
            "/profile/password",
            json={"current_password": PASSWORD, "new_password": new_password},
            expected=204,
        )
        other_session.get("/auth/me", expected=401)
        student.api.get("/auth/me", expected=401)
        student.api.login(student.email, new_password)
        student.api.post("/auth/logout", expected=204)
        student.api.get("/auth/me", expected=401)
    finally:
        other_session.close()


def test_catalog_resources_and_parameter_validation(users):
    student, admin = users(), users(role="admin")
    assert student.api.get("/courses").json()["items"]
    assert student.api.get("/courses/examples").json()["exercises"]
    exercise = student.api.get("/exercises/hello-c").json()
    assert exercise["subject"] and exercise["quota"]["remaining"] > 0
    resource = student.api.get(exercise["resources"][0]["download_url"])
    assert "attachment" in resource.headers["content-disposition"]
    student.api.get("/exercises/does-not-exist", expected=404)
    student.api.get("/evaluations/not-a-uuid", expected=422)
    for query in ("limit=0", "offset=-1", "status=invalid", "user_id=invalid"):
        admin.api.get("/admin/evaluations?" + query, expected=422)


def test_ssh_key_and_concurrent_start_stop(deployment, users):
    student = users(ssh_key=False)
    student.api.post("/exercises/hello-c/start", expected=409)
    student.api.put("/profile/ssh-key", json={"public_key": "ssh-rsa invalid"}, expected=400)
    student.api.put("/profile/ssh-key", json={"public_key": student.public_key})
    with ThreadPoolExecutor(max_workers=8) as executor:
        responses = list(
            executor.map(
                lambda _: student.api.post("/exercises/hello-c/start", expected=(200, 202, 409)),
                range(8),
            )
        )
    assert sum(r.status_code == 202 for r in responses) == 1
    env = student.wait_environment("running")
    assert len(deployment.containers(student.id, "development")) == 1
    assert "StrictHostKeyChecking=no" in env["ssh"]["command"]
    student.api.post("/exercises/hello-c/start")  # Same running exercise is idempotent.
    student.api.post("/exercises/sum-c/start", expected=409)
    student.api.put("/profile/ssh-key", json={"public_key": student.public_key}, expected=409)
    student.stop()
    student.api.put("/profile/ssh-key", json={"public_key": student.public_key})
    assert not deployment.containers(student.id)


def test_grading_admission_and_races(deployment, users):
    student = users()
    for exercise in (None, "sum-c", "stopped"):
        if exercise == "sum-c":
            student.start("sum-c")
        elif exercise == "stopped":
            student.stop()
        before = student.state()
        quota = student.api.get("/exercises/hello-c").json()["quota"]
        student.api.post("/exercises/hello-c/grade", expected=409)
        assert student.state() == before
        assert student.api.get("/exercises/hello-c").json()["quota"] == quota
        assert student.api.get("/exercises/hello-c/evaluations").json()["total"] == 0
    ssh = student.start()
    ssh.run("mkdir hello-c")
    ssh.write("hello-c/main.c", SLOW_HELLO)
    with ThreadPoolExecutor(max_workers=6) as executor:
        responses = list(
            executor.map(
                lambda _: student.api.post("/exercises/hello-c/grade", expected=(202, 409)),
                range(6),
            )
        )
    accepted = [r for r in responses if r.status_code == 202]
    assert len(accepted) == 1
    assert student.state()["locked"]
    student.api.post("/environment/stop", expected=409)
    student.api.post("/exercises/hello-c/start", expected=409)
    student.api.put("/profile/ssh-key", json={"public_key": student.public_key}, expected=409)
    assert student.report(accepted[0].json()["id"])["is_success"]
    # Stop and grade compete under the same student lock.
    student.start()
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda path: student.api.post(path, expected=(202, 409)),
                ["/environment/stop", "/exercises/hello-c/grade"],
            )
        )
    assert sorted(r.status_code for r in responses) == [202, 409]
    if responses[1].status_code == 202:
        student.report(responses[1].json()["id"])
    else:
        student.wait_environment("stopped")


def test_reports_snapshots_and_admin_cleanup(deployment, users):
    student, other, admin = users(), users(), users(role="admin")
    ssh = student.start()
    ssh.run("mkdir hello-c")
    ssh.write("hello-c/main.c", HELLO)
    evaluation_id = student.submit()
    report = student.report(evaluation_id)
    assert report["status"] == "completed" and report["is_success"]
    assert report["tests"] and report["snapshot_available"]
    assert student.snapshot(evaluation_id)["workspace/main.c"] == HELLO.encode()
    other.api.get(f"/evaluations/{evaluation_id}", expected=404)
    other.api.get(f"/evaluations/{evaluation_id}/snapshot", expected=404)
    rows = admin.api.get(f"/admin/evaluations?user_id={student.id}&exercise_id=hello-c").json()
    assert rows["total"] == 1 and rows["items"][0]["id"] == evaluation_id
    assert admin.api.get("/admin/stats").json()["successful_evaluations"] >= 1
    student.start()
    assert any(
        row["user_id"] == student.id for row in admin.api.get("/admin/environments").json()["items"]
    )
    admin.api.post(f"/admin/environments/{student.id}/clear", expected=202)
    student.wait_environment("stopped")
    assert not deployment.containers(student.id)


def test_quota_and_deadline(deployment, users):
    student = users()
    db = deployment.db
    original = db.rows("SELECT max_evaluations FROM exercises WHERE id='hello-c'")[0]
    deadline = db.rows("SELECT deadline FROM courses WHERE id='examples'")[0]["deadline"]
    try:
        db.execute("UPDATE exercises SET max_evaluations=1 WHERE id='hello-c';")
        ssh = student.start()
        ssh.run("mkdir hello-c")
        ssh.write("hello-c/main.c", HELLO)
        assert student.report(student.submit())["is_success"]
        student.start()
        response = student.api.post("/exercises/hello-c/grade", expected=429)
        assert int(response.headers["retry-after"]) > 0
        db.execute("UPDATE courses SET deadline=now()-interval '1 second' WHERE id='examples';")
        student.api.post("/exercises/hello-c/grade", expected=409)
        student.api.post("/exercises/sum-c/start", expected=409)
        student.stop()  # Stop remains available after a deadline.
        assert student.api.get("/exercises/hello-c/evaluations").json()["total"] == 1
    finally:
        db.execute(
            f"UPDATE exercises SET max_evaluations={original['max_evaluations']} WHERE id='hello-c';"
        )
        db.execute(f"UPDATE courses SET deadline={quote(deadline)} WHERE id='examples';")
