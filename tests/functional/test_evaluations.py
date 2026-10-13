"""Functional tests for grading, snapshot downloads, and history using Stuart & Dave."""


def test_grading_execution_and_snapshot_download(stuart):
    """Stuart submits hello-c for grading, inspects results, and downloads snapshot."""
    # Grade hello-c
    grade_res = stuart.client.post("/api/v1/exercises/hello-c/grade", headers=stuart.headers)
    assert grade_res.status_code == 200
    data = grade_res.json()

    assert data["environment"]["state"] == "stopped"
    evaluation = data["evaluation"]
    assert evaluation["exercise_id"] == "hello-c"
    assert evaluation["status"] == "completed"
    assert evaluation["total"] == 3
    assert len(evaluation["tests"]) == 3

    eval_id = evaluation["id"]

    # Query evaluation detail
    detail_res = stuart.client.get(f"/api/v1/evaluations/{eval_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["id"] == eval_id
    assert detail["exercise_name"] == "First C Program"

    # Download snapshot archive
    snapshot_res = stuart.client.get(f"/api/v1/evaluations/{eval_id}/snapshot")
    assert snapshot_res.status_code == 200
    assert snapshot_res.headers.get("Content-Type") == "application/gzip"
    assert len(snapshot_res.content) > 0


def test_evaluation_history_per_exercise(dave):
    """Dave evaluates an exercise and checks his per-exercise evaluation history."""
    # Run evaluation
    res = dave.client.post("/api/v1/exercises/fibo-c/grade", headers=dave.headers)
    assert res.status_code == 200
    eval_id = res.json()["evaluation"]["id"]

    # Check per-exercise history
    ex_hist_res = dave.client.get("/api/v1/exercises/fibo-c/evaluations")
    assert ex_hist_res.status_code == 200
    ex_evals = ex_hist_res.json()["evaluations"]
    assert any(e["id"] == eval_id for e in ex_evals)
