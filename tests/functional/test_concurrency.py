"""Functional tests for concurrency, student lock isolation, and collision prevention using Mel, Kevin, and Bob."""

from backend.src.state import get_runtime_manager


def test_independent_students_concurrency(kevin, bob, mel):
    """Multiple students perform concurrent environment and grading operations without inter-blocking."""
    # Kevin starts hello-c
    res_k = kevin.client.post("/api/v1/exercises/hello-c/start", headers=kevin.headers)
    assert res_k.status_code == 200

    # Bob starts fibo-c while Kevin's container is active
    res_b = bob.client.post("/api/v1/exercises/fibo-c/start", headers=bob.headers)
    assert res_b.status_code == 200

    # Mel grades hello-c concurrently
    res_m = mel.client.post("/api/v1/exercises/hello-c/grade", headers=mel.headers)
    assert res_m.status_code == 200

    # Verify Kevin and Bob are still running
    assert kevin.client.get("/api/v1/environment").json()["state"] == "running"
    assert bob.client.get("/api/v1/environment").json()["state"] == "running"

    # Stop environments
    kevin.client.post("/api/v1/environment/stop", headers=kevin.headers)
    bob.client.post("/api/v1/environment/stop", headers=bob.headers)


def test_single_student_operation_lock_collision(mel):
    """A student cannot execute concurrent mutating operations on their own environment."""
    lock = get_runtime_manager().get_student_lock(mel.id)

    # Simulate ongoing background operation by holding lock
    assert lock.acquire(blocking=False) is True
    try:
        # Status shows locked
        env_res = mel.client.get("/api/v1/environment")
        assert env_res.status_code == 200
        assert env_res.json()["locked"] is True

        # Mutating action while locked must fail with 409
        start_res = mel.client.post("/api/v1/exercises/hello-c/start", headers=mel.headers)
        assert start_res.status_code in (409, 503)
        assert start_res.json()["error"]["code"] in ("OPERATION_IN_PROGRESS", "STUDENT_LOCKED")
    finally:
        lock.release()

    # After release, Mel is unlocked
    assert mel.client.get("/api/v1/environment").json()["locked"] is False
