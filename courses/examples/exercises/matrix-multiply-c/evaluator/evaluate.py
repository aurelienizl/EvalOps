#!/usr/bin/env python3
"""Compile the submission and report each case using EvalOps schema version 1."""

import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

SOURCE_FILE = "matrix.c"
WORKSPACE_NAME = "matrix-multiply-c"
COMPILE_TIMEOUT_SECONDS = 10
RUN_TIMEOUT_SECONDS = 2


def matrix_case(case_id, name, a, b):
    rows, inner, cols = len(a), len(b), len(b[0])
    product = [
        [sum(a[i][k] * b[k][j] for k in range(inner)) for j in range(cols)] for i in range(rows)
    ]
    stdin = f"{rows} {inner} {cols}\n"
    stdin += "".join(" ".join(map(str, row)) + "\n" for row in a + b)
    stdout = "".join(" ".join(map(str, row)) + "\n" for row in product)
    return case_id, name, stdin, stdout


CASES = [
    matrix_case(
        "rectangular", "Rectangular matrices", [[1, 2, 3], [4, 5, 6]], [[7, 8], [9, 10], [11, 12]]
    ),
    matrix_case("scalar", "One element", [[-7]], [[6]]),
    matrix_case("identity", "Identity matrix", [[2, -3], [4, 5]], [[1, 0], [0, 1]]),
    matrix_case("zero", "Zero product", [[0, 0], [0, 0]], [[2, 3], [4, 5]]),
    matrix_case("outer", "Column times row", [[2], [-1], [3]], [[4, 0, -2]]),
    matrix_case("dot", "Row times column", [[1, -2, 3]], [[4], [5], [-6]]),
    matrix_case(
        "bounds",
        "Maximum dimensions and values",
        [[100] * 10 for _ in range(10)],
        [[-100] * 10 for _ in range(10)],
    ),
    matrix_case(
        "varied",
        "Distinct row and column dimensions",
        [[(i * 3 + j) % 9 - 4 for j in range(7)] for i in range(4)],
        [[(i + j * 2) % 7 - 3 for j in range(5)] for i in range(7)],
    ),
]


def evaluate(workspace_dir: Path) -> dict:
    workspace_dir = workspace_dir.resolve()
    source = workspace_dir / SOURCE_FILE
    exists = source.is_file()
    tests = [
        {
            "id": "file_exists",
            "name": f"Source file {SOURCE_FILE} exists",
            "passed": exists,
            "message": None if exists else f"Source file {SOURCE_FILE} is missing",
        }
    ]

    # Never compile into the read-only student workspace or reuse an old binary.
    with TemporaryDirectory(prefix="evalops-c-") as directory:
        binary = Path(directory) / "submission"
        compiled = False
        message = f"Source file {SOURCE_FILE} is missing"
        if exists:
            try:
                result = subprocess.run(
                    ["gcc", "-std=c11", "-Wall", "-Wextra", str(source), "-o", str(binary)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=workspace_dir,
                    timeout=COMPILE_TIMEOUT_SECONDS,
                )
                compiled = result.returncode == 0
                message = None if compiled else result.stderr[:2000].replace("\x00", "\\x00")
            except subprocess.TimeoutExpired:
                message = "Compilation timed out"
            except OSError as error:
                message = f"Compilation failed: {error}"
        tests.append(
            {
                "id": "compilation",
                "name": f"Compile {SOURCE_FILE} with gcc",
                "passed": compiled,
                "message": message,
            }
        )

        for case_id, name, stdin, expected in CASES:
            passed = False
            message = "Compilation not successful"
            return_code = None
            if compiled:
                try:
                    result = subprocess.run(
                        [str(binary)],
                        input=stdin.encode("utf-8"),
                        capture_output=True,
                        cwd=workspace_dir,
                        timeout=RUN_TIMEOUT_SECONDS,
                    )
                    stdout = result.stdout.decode("utf-8", errors="replace")
                    return_code = result.returncode
                    passed = return_code == 0 and stdout == expected
                    message = (
                        None
                        if passed
                        else (
                            f"Expected stdout {expected!r}; got {stdout[:1000]!r} "
                            f"(exit code {return_code})"
                        )
                    )
                except subprocess.TimeoutExpired:
                    message = f"Execution timed out after {RUN_TIMEOUT_SECONDS} seconds"
                except OSError as error:
                    message = f"Execution failed: {error}"
            tests.append(
                {
                    "id": case_id,
                    "name": name,
                    "passed": passed,
                    "message": message,
                    "return_code": return_code,
                }
            )
    return {"schema_version": 1, "tests": tests}


def main():
    workspace = Path(os.environ.get("WORKSPACE_DIR", f"/home/student/{WORKSPACE_NAME}"))
    result_dir = Path(os.environ.get("RESULT_DIR", "/result"))
    result_dir.mkdir(parents=True, exist_ok=True)
    temporary = result_dir / "result.json.tmp"
    temporary.write_text(json.dumps(evaluate(workspace), indent=2), encoding="utf-8")
    temporary.replace(result_dir / "result.json")


if __name__ == "__main__":
    main()
