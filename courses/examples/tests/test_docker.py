"""Opt-in image and trusted sandbox checks, independent of the running stack."""

import json
import os
import shutil
import subprocess
import time
from uuid import uuid4

import pytest

from helpers import EXAMPLES, EXERCISES, load_evaluator, print_program, solution, validate_report

pytestmark = pytest.mark.skipif(
    os.environ.get("EVALOPS_EXAMPLE_DOCKER_TESTS") != "1",
    reason="Set EVALOPS_EXAMPLE_DOCKER_TESTS=1 to build and run the exercise images",
)


def docker(*args, check=True, timeout=60):
    result = subprocess.run(
        ["docker", *map(str, args)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode:
        pytest.fail(f"docker {args[0]} failed:\n{result.stdout}\n{result.stderr}")
    return result


@pytest.fixture(scope="module", params=EXERCISES)
def images(request, tmp_path_factory):
    exercise = request.param
    prefix = f"evalops-example-test-{uuid4().hex[:12]}"
    dev, evaluator, wrapped = (f"{prefix}:{kind}" for kind in ("dev", "evaluator", "sandbox"))
    context = tmp_path_factory.mktemp("example-sandbox")
    repo = EXAMPLES.parents[1]
    shutil.copyfile(repo / "container_manager/src/grading/sandbox_runner.py", context / "runner.py")
    (context / "Dockerfile").write_text(
        f'FROM {evaluator}\nCOPY runner.py /runner.py\nENTRYPOINT ["python3", "-I", "/runner.py"]\n'
    )
    try:
        for kind, tag in (("dev", dev), ("evaluator", evaluator)):
            print(f"\nBuilding {exercise}/{kind}", flush=True)
            docker("build", "-t", tag, EXAMPLES / "exercises" / exercise / kind, timeout=600)
        docker("build", "-t", wrapped, context, timeout=120)
        yield exercise, dev, wrapped
    finally:
        docker("image", "rm", "--force", wrapped, evaluator, dev, check=False)


def test_development_image_starts_ssh_and_can_compile_as_student(images, tmp_path):
    exercise, dev, _ = images
    container = docker("run", "-d", "--network", "none", "--memory", "256m", dev).stdout.strip()
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            health = docker(
                "inspect", "--format", "{{.State.Health.Status}}", container
            ).stdout.strip()
            if health == "healthy":
                break
            time.sleep(0.2)
        else:
            pytest.fail("SSH did not become healthy:\n" + docker("logs", container).stderr)
        source = tmp_path / "reference.c"
        source.write_text(solution(exercise))
        docker("cp", source, f"{container}:/tmp/reference.c")
        docker(
            "exec",
            "--user",
            "1000:1000",
            container,
            "gcc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "/tmp/reference.c",
            "-o",
            f"/home/student/{exercise}/app",
        )
        stdin, expected = load_evaluator(exercise).CASES[0][2:]
        run = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                "--user",
                "1000:1000",
                container,
                f"/home/student/{exercise}/app",
            ],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert run.returncode == 0, run.stderr
        assert run.stdout == expected
    finally:
        docker("rm", "--force", container, check=False)


@pytest.mark.parametrize("kind", ["correct", "wrong", "invalid_c", "missing"])
def test_evaluator_in_the_production_sandbox(images, tmp_path, kind):
    exercise, _, image = images
    evaluator = load_evaluator(exercise)
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o755)
    source = workspace / evaluator.SOURCE_FILE
    if kind == "correct":
        source.write_text(solution(exercise))
    elif kind == "wrong":
        source.write_text(print_program("incorrect\n"))
    elif kind == "invalid_c":
        source.write_text("not valid C\n")
    original = source.read_bytes() if source.exists() else None
    container = docker(
        "run",
        "-d",
        "--network",
        "none",
        "--read-only",
        "--user",
        "0:0",
        "--cap-drop",
        "ALL",
        "--cap-add",
        "CHOWN",
        "--cap-add",
        "DAC_OVERRIDE",
        "--cap-add",
        "FOWNER",
        "--cap-add",
        "SETUID",
        "--cap-add",
        "SETGID",
        "--cap-add",
        "KILL",
        "--security-opt",
        "no-new-privileges:true",
        "--pids-limit",
        "64",
        "--memory",
        "256m",
        "--tmpfs",
        "/tmp:rw,exec,nosuid,nodev,size=134217728,mode=1777",
        "--tmpfs",
        "/result:rw,nosuid,nodev,noexec,size=2097152,mode=0700",
        "--mount",
        f"type=bind,src={workspace},dst=/home/student/{exercise},readonly",
        "-e",
        f"WORKSPACE_DIR=/home/student/{exercise}",
        "-e",
        "RESULT_DIR=/result",
        image,
    ).stdout.strip()
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            marker = docker("exec", container, "cat", "/result/exit_code", check=False)
            if marker.returncode == 0:
                assert marker.stdout.strip() == "0", docker("logs", container).stderr
                break
            time.sleep(0.1)
        else:
            pytest.fail("Evaluator did not finish:\n" + docker("logs", container).stderr)
        report = validate_report(
            json.loads(docker("exec", container, "cat", "/result/result.json").stdout)
        )
        assert report.is_success == (kind == "correct"), report
        assert report.total_tests == 2 + len(evaluator.CASES)
        assert (source.read_bytes() if source.exists() else None) == original
        assert not (workspace / "submission").exists()
        # The student UID cannot change the trusted report directory.
        assert (
            docker(
                "exec", "--user", "1000:1000", container, "test", "-w", "/result", check=False
            ).returncode
            != 0
        )
    finally:
        docker("rm", "--force", container, check=False)
