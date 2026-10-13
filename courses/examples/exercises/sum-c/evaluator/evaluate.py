#!/usr/bin/env python3
import json
import os
import subprocess
from pathlib import Path


def evaluate(workspace_dir: Path) -> dict:
    source_file = workspace_dir / "sum.c"
    binary_path = Path("/tmp/sum")
    file_exists = source_file.is_file()
    tests = [{
        "id": "file_exists",
        "name": "Source file sum.c exists",
        "passed": file_exists,
        "message": None if file_exists else "Source file sum.c is missing",
    }]

    compiled = False
    message = "Source file sum.c is missing"
    if file_exists:
        try:
            result = subprocess.run(
                ["gcc", "-Wall", "-Wextra", str(source_file), "-o", str(binary_path)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            compiled = result.returncode == 0
            message = None if compiled else result.stderr.strip()
        except (OSError, subprocess.TimeoutExpired) as error:
            message = f"Compilation failed: {error}"
    tests.append({
        "id": "compilation",
        "name": "Compile sum.c with gcc",
        "passed": compiled,
        "message": message,
    })

    correct_output = False
    message = "Compilation not successful"
    if compiled:
        correct_output = True
        message = None
        for input_text, expected in [("2 3\n", "5"), ("-4 7\n", "3"), ("0 0\n", "0")]:
            try:
                result = subprocess.run(
                    [str(binary_path)],
                    input=input_text,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                actual = result.stdout.strip()
                if result.returncode != 0 or actual != expected:
                    correct_output = False
                    message = (
                        f"Input {input_text.strip()!r}: expected {expected!r}, "
                        f"got {actual!r} (exit code {result.returncode})"
                    )
                    break
            except (OSError, subprocess.TimeoutExpired, UnicodeError) as error:
                correct_output = False
                message = f"Execution failed: {error}"
                break
    tests.append({
        "id": "correct_output",
        "name": "Correct sums for positive, negative, and zero inputs",
        "passed": correct_output,
        "message": message,
    })
    return {"schema_version": 1, "tests": tests}


def main():
    workspace_dir = Path(os.environ.get("WORKSPACE_DIR", "/home/student/sum-c"))
    result_dir = Path("/result")
    result_dir.mkdir(parents=True, exist_ok=True)
    temporary_file = result_dir / "result.json.tmp"
    temporary_file.write_text(json.dumps(evaluate(workspace_dir)), encoding="utf-8")
    temporary_file.replace(result_dir / "result.json")


if __name__ == "__main__":
    main()
