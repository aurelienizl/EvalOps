"""Evaluator JSON contracts and binary success rules; no score or point logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TestResult:
    source_id: str
    name: str
    status: Literal["passed", "failed", "error"]
    message: str | None = None
    return_code: int | None = None
    stdout_diff: str | None = None
    stderr_diff: str | None = None
    execution_time_ms: int | None = None


@dataclass(frozen=True)
class EvaluationReport:
    tests: tuple[TestResult, ...]
    passed_tests: int
    total_tests: int
    is_success: bool


def parse_result(data, max_bytes):
    import json

    if len(data) > max_bytes:
        raise ValueError("Result exceeds size limit")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("Non-finite JSON number")

    value = json.loads(data, object_pairs_hook=unique, parse_constant=invalid)
    if (
        not isinstance(value, dict)
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
    ):
        raise ValueError("Unsupported result schema")
    rows = value.get("tests")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 200:
        raise ValueError("Expected 1-200 tests")
    tests = []
    ids = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid test")
        source_id = row.get("id")
        name = row.get("name")
        if (
            not isinstance(source_id, str)
            or not source_id.strip()
            or len(source_id) > 128
            or source_id in ids
        ):
            raise ValueError("Invalid/duplicate test ID")
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name) > 255
            or "\x00" in name
            or type(row.get("passed")) is not bool
        ):
            raise ValueError("Invalid test name/status")
        ids.add(source_id)
        for key in ("message", "stdout_diff", "stderr_diff"):
            text = row.get(key)
            if text is not None and (
                not isinstance(text, str) or len(text.encode()) > 16384 or "\x00" in text
            ):
                raise ValueError("Invalid test text")
        for key in ("return_code", "execution_time_ms"):
            number = row.get(key)
            if number is not None and (
                type(number) is not int
                or not -2147483648 <= number <= 2147483647
                or key == "execution_time_ms"
                and number < 0
            ):
                raise ValueError("Invalid test metric")
        tests.append(
            TestResult(
                source_id,
                name,
                "passed" if row["passed"] else "failed",
                row.get("message"),
                row.get("return_code"),
                row.get("stdout_diff"),
                row.get("stderr_diff"),
                row.get("execution_time_ms"),
            )
        )
    passed = sum(test.status == "passed" for test in tests)
    return EvaluationReport(tuple(tests), passed, len(tests), passed == len(tests))


def classify_outcome(outcome, report):
    if outcome.timed_out:
        return "timeout"
    if outcome.oom_killed or outcome.exit_code != 0 or report is None:
        return "failed"
    return "completed"
