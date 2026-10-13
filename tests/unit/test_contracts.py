"""Invalid manager inputs/results must not become paths or successful scores."""

import pytest
from pydantic import ValidationError

from shared.contracts import EvaluatorOutput, EvaluatorTestResult, ManagerGradeRequest, ManagerOperation, ManagerStartRequest


@pytest.mark.parametrize("identifier", ["../escape", "a/b", "a\\b", ".hidden", "", "a\n"])
def test_operation_identifiers_reject_unsafe_path_components(identifier):
    with pytest.raises(ValidationError):
        ManagerGradeRequest(operation_id=identifier, exercise_id="hello-c")


@pytest.mark.parametrize("passed", ["true", "false", 1, 0, None])
def test_evaluator_results_require_boolean_success(passed):
    with pytest.raises(ValidationError):
        EvaluatorTestResult(id="test", passed=passed)


@pytest.mark.parametrize("started_at", [float("nan"), float("inf"), -1, 1e30])
def test_manager_operation_timestamp_is_renderable(started_at):
    with pytest.raises(ValidationError):
        ManagerOperation(operation_id="op", type="grade", status="running", started_at=started_at)


@pytest.mark.parametrize("key", [None, ""])
def test_start_requires_ssh_key(key):
    with pytest.raises(ValidationError):
        ManagerStartRequest(operation_id="op", exercise_id="hello-c", ssh_public_key=key)


def test_evaluator_requires_current_schema_version():
    with pytest.raises(ValidationError):
        EvaluatorOutput(tests=[])
