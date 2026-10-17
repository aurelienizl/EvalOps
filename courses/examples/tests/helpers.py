"""Reference submissions are test fixtures, never downloadable course resources."""

import importlib.util
import json
from pathlib import Path

from container_manager.src.grading.results import parse_result

EXAMPLES = Path(__file__).resolve().parents[1]
EXERCISES = (
    "hello-c",
    "square-c",
    "sum-c",
    "fibo-c",
    "palindrome-c",
    "sort-c",
    "matrix-multiply-c",
    "shortest-path-c",
)


def load_evaluator(exercise):
    path = EXAMPLES / "exercises" / exercise / "evaluator/evaluate.py"
    spec = importlib.util.spec_from_file_location(exercise.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def solution(exercise):
    return (EXAMPLES / "tests/solutions" / f"{exercise}.c").read_text()


def print_program(output, exit_code=0):
    literal = json.dumps(output)
    return f"#include <stdio.h>\nint main(void){{fputs({literal}, stdout);return {exit_code};}}\n"


def validate_report(report):
    return parse_result(json.dumps(report).encode(), 1024 * 1024)
