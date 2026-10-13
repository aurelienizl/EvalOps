"""Functional tests for error handling, security checks, and rate limits using Otto."""

from fastapi.testclient import TestClient


def test_authentication_and_csrf_enforcement(otto, functional_instance):
    """Endpoints strictly enforce authentication and CSRF headers."""
    unauth_client = TestClient(functional_instance["app"])

    # 1. Unauthenticated request -> 401
    res_unauth = unauth_client.get("/api/v1/auth/me")
    assert res_unauth.status_code == 401
    assert res_unauth.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

    # 2. Mutating request without CSRF -> 403
    res_no_csrf = otto.client.post("/api/v1/environment/stop")
    assert res_no_csrf.status_code == 403
    assert res_no_csrf.json()["error"]["code"] == "CSRF_INVALID"


def test_invalid_ssh_keys_rejected(otto):
    """Malformed, RSA, or commented SSH keys are rejected with 422."""
    # RSA key
    res_rsa = otto.client.put(
        "/api/v1/profile/ssh-key",
        headers=otto.headers,
        json={"public_key": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC invalid"},
    )
    assert res_rsa.status_code == 422
    assert res_rsa.json()["error"]["code"] == "INVALID_SSH_KEY"

    # Comment in key
    res_comment = otto.client.put(
        "/api/v1/profile/ssh-key",
        headers=otto.headers,
        json={"public_key": f"{otto.ssh_public_key} otto@laptop"},
    )
    assert res_comment.status_code == 422
    assert res_comment.json()["error"]["code"] == "INVALID_SSH_KEY"


def test_cross_student_evaluation_isolation(otto, stuart):
    """Otto cannot inspect or download Stuart's evaluation (returns strict 404)."""
    # Stuart creates an evaluation
    grade_res = stuart.client.post("/api/v1/exercises/hello-c/grade", headers=stuart.headers)
    assert grade_res.status_code == 200
    stuart_eval_id = grade_res.json()["evaluation"]["id"]

    # Otto tries to access Stuart's evaluation -> 404
    res_leak = otto.client.get(f"/api/v1/evaluations/{stuart_eval_id}")
    assert res_leak.status_code == 404
    assert res_leak.json()["error"]["code"] == "EVALUATION_NOT_FOUND"

    # Otto tries to download Stuart's snapshot -> 404
    snap_leak = otto.client.get(f"/api/v1/evaluations/{stuart_eval_id}/snapshot")
    assert snap_leak.status_code == 404


def test_missing_resources_returns_404(otto):
    """Non-existent courses, exercises, or snapshots return 404."""
    assert otto.client.get("/api/v1/courses/non-existent-course").status_code == 404
    assert otto.client.get("/api/v1/exercises/non-existent-exercise").status_code == 404
    assert otto.client.get("/api/v1/evaluations/00000000-0000-0000-0000-000000000000/snapshot").status_code == 404


def test_evaluation_quota_rate_limiting(mel):
    """Mel exhausts her evaluation quota and receives 429 EVALUATION_RATE_LIMITED."""
    ex_res = mel.client.get("/api/v1/exercises/hello-c")
    assert ex_res.status_code == 200
    quota = ex_res.json()["evaluation_quota"]
    max_evals = quota["max_evaluations"]

    # Submit up to quota limit
    for _ in range(quota["remaining"]):
        res = mel.client.post("/api/v1/exercises/hello-c/grade", headers=mel.headers)
        assert res.status_code == 200

    # Next submission must be rate-limited (429)
    blocked_res = mel.client.post("/api/v1/exercises/hello-c/grade", headers=mel.headers)
    assert blocked_res.status_code == 429
    assert blocked_res.json()["error"]["code"] == "EVALUATION_RATE_LIMITED"
    assert blocked_res.headers.get("Retry-After") is not None
