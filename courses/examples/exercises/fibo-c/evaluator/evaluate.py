#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from pathlib import Path

def main():
    workspace_dir = Path(os.environ.get("WORKSPACE_DIR", "/home/student/fibo-c"))
    source_file = workspace_dir / "fibo.c"
    binary_path = Path("/tmp/fibo")

    tests = []

    # Test 1: file_exists
    file_exists = False
    if not source_file.exists():
        tests.append({
            "id": "file_exists",
            "name": "Source file fibo.c exists",
            "passed": False,
            "message": f"File '{source_file.name}' not found in {workspace_dir}"
        })
    else:
        file_exists = True
        tests.append({
            "id": "file_exists",
            "name": "Source file fibo.c exists",
            "passed": True,
            "message": None
        })

    # Test 2: compilation
    compiled = False
    if not file_exists:
        tests.append({
            "id": "compilation",
            "name": "Compile fibo.c with gcc",
            "passed": False,
            "message": "Source file missing"
        })
    else:
        try:
            res = subprocess.run(
                ["gcc", "-Wall", "-Wextra", str(source_file), "-o", str(binary_path)],
                capture_output=True,
                text=True,
                timeout=10
            )
            if res.returncode == 0:
                compiled = True
                tests.append({
                    "id": "compilation",
                    "name": "Compile fibo.c with gcc",
                    "passed": True,
                    "message": None
                })
            else:
                tests.append({
                    "id": "compilation",
                    "name": "Compile fibo.c with gcc",
                    "passed": False,
                    "message": f"Compilation error:\n{res.stderr.strip()}"
                })
        except Exception as e:
            tests.append({
                "id": "compilation",
                "name": "Compile fibo.c with gcc",
                "passed": False,
                "message": f"Compilation failed: {e}"
            })

    # Test 3: test_values
    if not compiled:
        tests.append({
            "id": "test_values",
            "name": "Correct Fibonacci sequence (terms 0 to 9)",
            "passed": False,
            "message": "Compilation not successful"
        })
    else:
        try:
            run_res = subprocess.run(
                [str(binary_path)],
                capture_output=True,
                text=True,
                timeout=5
            )
            expected = "0 1 1 2 3 5 8 13 21 34"
            actual = " ".join(run_res.stdout.split())
            if expected in actual:
                tests.append({
                    "id": "test_values",
                    "name": "Correct Fibonacci sequence (terms 0 to 9)",
                    "passed": True,
                    "message": None
                })
            else:
                tests.append({
                    "id": "test_values",
                    "name": "Correct Fibonacci sequence (terms 0 to 9)",
                    "passed": False,
                    "message": f"Expected: '{expected}', got: '{actual}'"
                })
        except Exception as e:
            tests.append({
                "id": "test_values",
                "name": "Correct Fibonacci sequence (terms 0 to 9)",
                "passed": False,
                "message": f"Execution error: {e}"
            })

    output_data = {
        "schema_version": 1,
        "tests": tests
    }

    result_dir = Path("/result")
    result_dir.mkdir(parents=True, exist_ok=True)
    temp_file = result_dir / "result.json.tmp"
    final_file = result_dir / "result.json"

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    temp_file.replace(final_file)
    sys.exit(0)

if __name__ == "__main__":
    main()
