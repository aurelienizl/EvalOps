"""Exercise real gcc builds and execution, including incorrect submissions."""

from collections import Counter
import json
import os
import re
import shutil
import subprocess
import sys
from unittest.mock import patch

import pytest

from container_manager.src.catalog.loader import discover_catalog
from helpers import EXAMPLES, EXERCISES, load_evaluator, print_program, solution, validate_report


@pytest.fixture(params=EXERCISES)
def submission(request, tmp_path):
    exercise = request.param
    evaluator = load_evaluator(exercise)
    workspace = tmp_path / exercise
    workspace.mkdir()
    source = workspace / evaluator.SOURCE_FILE
    source.write_text(solution(exercise))
    return evaluator, workspace, source


def test_catalog_has_two_exercises_per_difficulty_and_real_resources(tmp_path):
    courses = tmp_path / "courses"
    shutil.copytree(
        EXAMPLES,
        courses / "examples",
        ignore=shutil.ignore_patterns(
            "tests",
            "__pycache__",
            ".pytest_cache",
        ),
    )
    (course,) = discover_catalog(courses)
    assert course.id == "examples"
    assert {ex.id for ex in course.exercises} == set(EXERCISES)
    assert Counter(ex.difficulty for ex in course.exercises) == {
        "warmup": 2,
        "easy": 2,
        "medium": 2,
        "hard": 2,
    }
    for exercise in course.exercises:
        assert exercise.resources
        for resource in exercise.resources:
            assert resource.file_path.suffix == ".md"
            assert resource.file_path.read_text().strip()


def test_correct_reference_solution_passes_every_case(submission):
    evaluator, workspace, _ = submission
    report = validate_report(evaluator.evaluate(workspace))
    assert report.is_success, report
    assert report.total_tests == 2 + len(evaluator.CASES)
    assert len({case[0] for case in evaluator.CASES}) == len(evaluator.CASES)


@pytest.mark.parametrize("source_kind", ["missing", "directory", "invalid_c"])
def test_unusable_source_produces_a_complete_failed_report(submission, source_kind):
    evaluator, workspace, source = submission
    source.unlink()
    if source_kind == "directory":
        source.mkdir()
    elif source_kind == "invalid_c":
        source.write_text("this is not valid C;\n")
    report = validate_report(evaluator.evaluate(workspace))
    assert not report.is_success
    assert report.total_tests == 2 + len(evaluator.CASES)
    assert report.tests[0].status == ("passed" if source_kind == "invalid_c" else "failed")
    assert all(test.status == "failed" for test in report.tests[1:])


@pytest.mark.parametrize(
    "mistake",
    [
        "wrong_output",
        "prefix",
        "suffix",
        "missing_newline",
        "crlf",
        "nonzero_exit",
        "invalid_utf8",
    ],
)
def test_output_and_exit_status_are_checked_strictly(submission, mistake):
    evaluator, workspace, source = submission
    expected = evaluator.CASES[0][3]
    output = {
        "wrong_output": "incorrect\n",
        "prefix": "extra " + expected,
        "suffix": expected + "extra\n",
        "missing_newline": expected.removesuffix("\n"),
        "crlf": expected.replace("\n", "\r\n"),
        "nonzero_exit": expected,
        "invalid_utf8": "",
    }[mistake]
    source.write_text(print_program(output, exit_code=9 if mistake == "nonzero_exit" else 0))
    if mistake == "invalid_utf8":
        source.write_text("#include <stdio.h>\nint main(void){putchar(255);return 0;}\n")
    report = validate_report(evaluator.evaluate(workspace))
    assert [test.status for test in report.tests[:2]] == ["passed", "passed"]
    assert report.tests[2].status == "failed"
    assert report.tests[2].message
    assert not report.is_success


def test_runtime_timeout_is_reported_for_every_case(submission):
    evaluator, workspace, source = submission
    source.write_text("int main(void){for (;;) {}}\n")
    with patch.object(evaluator, "RUN_TIMEOUT_SECONDS", 0.03):
        report = validate_report(evaluator.evaluate(workspace))
    assert not report.is_success
    for test in report.tests[2:]:
        assert test.status == "failed"
        assert "timed out" in test.message


@pytest.mark.parametrize(
    "error",
    [
        subprocess.TimeoutExpired("gcc", 10),
        FileNotFoundError("gcc unavailable"),
    ],
)
def test_compiler_failure_is_reported(submission, error):
    evaluator, workspace, _ = submission
    with patch.object(evaluator.subprocess, "run", side_effect=error):
        report = validate_report(evaluator.evaluate(workspace))
    assert not report.is_success
    assert all(test.status == "failed" for test in report.tests[1:])
    assert report.tests[1].message


def test_successful_binary_cannot_be_reused_after_a_compile_failure(submission):
    evaluator, workspace, source = submission
    assert validate_report(evaluator.evaluate(workspace)).is_success
    source.write_text("invalid C\n")
    report = validate_report(evaluator.evaluate(workspace))
    assert all(test.status == "failed" for test in report.tests[1:])


def test_command_line_writes_a_valid_atomic_result_file(submission, tmp_path):
    evaluator, workspace, _ = submission
    result_dir = tmp_path / "custom-results"
    result_dir.mkdir()
    (result_dir / "result.json").write_text("outdated report")
    env = dict(os.environ, WORKSPACE_DIR=str(workspace), RESULT_DIR=str(result_dir))
    subprocess.run([sys.executable, evaluator.__file__], env=env, check=True, timeout=45)
    assert validate_report(json.loads((result_dir / "result.json").read_text())).is_success
    assert not (result_dir / "result.json.tmp").exists()
    assert sorted(path.name for path in workspace.iterdir()) == [evaluator.SOURCE_FILE]


@pytest.mark.parametrize(
    "exercise,old,new,failed_case",
    [
        ("square-c", "value * value", "value + value", "positive"),
        ("sum-c", "a + b", "a - b", "positive"),
        ("palindrome-c", "i < length / 2", "i < 1 && i < length / 2", "inner_mismatch"),
        (
            "palindrome-c",
            "line[i] != line[length - 1 - i]",
            "(line[i] | 32) != (line[length - 1 - i] | 32)",
            "case_sensitive",
        ),
        ("sort-c", "return (a > b) - (a < b)", "return (a < b) - (a > b)", "mixed"),
        ("sort-c", "qsort(values, count, sizeof *values, compare);", "", "reverse"),
        ("matrix-multiply-c", "k < inner", "k < inner - 1", "rectangular"),
        ("matrix-multiply-c", "int total = 0", "int total = 1", "zero"),
        ("shortest-path-c", "if (weight < weights[a][b])", "if (1)", "parallel"),
        (
            "shortest-path-c",
            "weights[a][b] = weight;",
            "weights[a][b] = weight; weights[b][a] = weight;",
            "directed",
        ),
        (
            "shortest-path-c",
            "if (weight < weights[a][b])",
            "if (weight > 0 && weight < weights[a][b])",
            "zero_weights",
        ),
    ],
)
def test_cases_reject_common_algorithm_mistakes(tmp_path, exercise, old, new, failed_case):
    evaluator = load_evaluator(exercise)
    correct = solution(exercise)
    assert old in correct
    (tmp_path / evaluator.SOURCE_FILE).write_text(correct.replace(old, new))
    report = validate_report(evaluator.evaluate(tmp_path))
    assert report.tests[1].status == "passed"
    assert next(test for test in report.tests if test.source_id == failed_case).status == "failed"


@pytest.mark.parametrize("exercise", EXERCISES)
def test_readme_example_matches_the_reference_solution(tmp_path, exercise):
    evaluator = load_evaluator(exercise)
    readme = (EXAMPLES / "exercises" / exercise / "README.md").read_text()
    samples = re.findall(r"```text\n(.*?)```", readme, re.DOTALL)
    stdin, expected = ("", samples[1]) if len(samples) == 2 else samples[1:]
    source = tmp_path / evaluator.SOURCE_FILE
    source.write_text(solution(exercise))
    binary = tmp_path / "app"
    subprocess.run(
        ["gcc", "-std=c11", "-Wall", "-Wextra", str(source), "-o", str(binary)],
        check=True,
        timeout=10,
    )
    result = subprocess.run([str(binary)], input=stdin, capture_output=True, text=True, timeout=2)
    assert result.returncode == 0
    assert result.stdout == expected
