"""Repeatable capacity simulation against an isolated Docker deployment."""

import json
import math
import random
import statistics
import tarfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest

EXERCISES = ("hello-c", "fibo-c", "sum-c")
SOURCES = {
    "hello-c": (
        "main.c",
        '#include <stdio.h>\nint main(void) { puts("Hello C"); return 0; }\n',
    ),
    "fibo-c": (
        "fibo.c",
        '#include <stdio.h>\nint main(void) { puts("0 1 1 2 3 5 8 13 21 34"); return 0; }\n',
    ),
    "sum-c": (
        "sum.c",
        '#include <stdio.h>\nint main(void) { int a, b; if (scanf("%d %d", &a, &b) != 2) return 1; printf("%d\\n", a + b); return 0; }\n',
    ),
}
WRONG_SOURCE = '#include <stdio.h>\nint main(void) { puts("wrong"); return 0; }\n'


def exercise_order(index: int, student_count: int) -> tuple[str, ...]:
    """Contiguous balanced groups, each visiting every exercise exactly once."""
    if student_count < 1 or not 0 <= index < student_count:
        raise ValueError("Student index must belong to a nonempty cohort")
    size, remainder = divmod(student_count, len(EXERCISES))
    upper_bound = 0
    for group in range(len(EXERCISES)):
        upper_bound += size + (group < remainder)
        if index < upper_bound:
            return EXERCISES[group:] + EXERCISES[:group]
    raise AssertionError("Unassigned student")


def success_attempt(seed: int, student_index: int, exercise_id: str) -> int:
    """First chance 1/3; conditional second chance 1/2; third guaranteed."""
    rng = random.Random(f"{seed}:{student_index}:{exercise_id}")
    if rng.randrange(3) == 0:
        return 1
    return 2 if rng.randrange(2) == 0 else 3


def _json(response, context):
    assert response.status_code == 200, (
        f"{context}: {response.status_code} {response.text}"
    )
    return response.json()


def _write_source(instance, student, exercise_id, correct):
    filename, source = SOURCES[exercise_id]
    source = (source if correct else WRONG_SOURCE).encode("utf-8")
    archive_bytes = BytesIO()
    with tarfile.open(fileobj=archive_bytes, mode="w") as archive:
        directory = tarfile.TarInfo(exercise_id)
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o775
        directory.uid = directory.gid = 1000
        archive.addfile(directory)
        file = tarfile.TarInfo(f"{exercise_id}/{filename}")
        file.size = len(source)
        file.mode = 0o664
        file.uid = file.gid = 1000
        archive.addfile(file, BytesIO(source))
    container = instance.docker_client.containers.get(
        f"devops-{instance.platform_instance}-dev-{student.id}"
    )
    assert container.put_archive("/home/student", archive_bytes.getvalue())


def _start(student, exercise_id):
    started = time.perf_counter()
    result = _json(
        student.client.post(
            f"/api/v1/exercises/{exercise_id}/start", headers=student.headers
        ),
        f"Start {student.name}/{exercise_id}",
    )
    assert result["state"] == "running"
    assert result["exercise"]["id"] == exercise_id
    return result["ssh"]["port"], time.perf_counter() - started


def _submit(instance, student, exercise_id, correct):
    _write_source(instance, student, exercise_id, correct)
    started = time.perf_counter()
    result = _json(
        student.client.post(
            f"/api/v1/exercises/{exercise_id}/grade", headers=student.headers
        ),
        f"Grade {student.name}/{exercise_id}",
    )
    evaluation = result["evaluation"]
    assert result["environment"]["state"] == "stopped"
    assert evaluation["status"] == "completed"
    assert evaluation["exercise_id"] == exercise_id
    assert evaluation["success"] is correct, (
        f"Unexpected score for {student.name}/{exercise_id}"
    )
    assert evaluation["total"] == 3
    assert evaluation["passed"] == (3 if correct else 2)
    return evaluation["id"], time.perf_counter() - started


def _latencies(values):
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "median_seconds": round(statistics.median(ordered), 3),
        "p95_seconds": round(ordered[math.ceil(len(ordered) * 0.95) - 1], 3),
        "max_seconds": round(ordered[-1], 3),
    }


@pytest.mark.capacity
def test_students_concurrent_journey(
    simulation_instance, pytestconfig, record_property
):
    instance = simulation_instance
    students = instance.students
    count = len(students)
    seed = pytestconfig.getoption("simulation_seed")
    journeys = {
        student.id: exercise_order(index, count)
        for index, student in enumerate(students)
    }
    attempts = {
        (student.id, exercise): success_attempt(seed, index, exercise)
        for index, student in enumerate(students)
        for exercise in EXERCISES
    }
    report = {
        "students": count,
        "seed": seed,
        "exercise_order": list(EXERCISES),
        "rounds": [],
        "peak_running_environments": 0,
        "start_latency": {},
        "grade_latency": {},
        "evaluations": 0,
        "status": "running",
    }
    docker_info = instance.docker_client.info()
    report["docker_host"] = {
        "cpus": docker_info["NCPU"],
        "memory_bytes": docker_info["MemTotal"],
    }
    report_path = instance.artifacts_path / "simulation-report.json"
    start_latencies, grade_latencies = [], []
    evaluation_ids = set()
    started = time.perf_counter()
    print(
        f"\nCapacity simulation: {count} students, seed {seed}, report {report_path}",
        flush=True,
    )
    try:
        assert (
            instance.query("SELECT COUNT(*) AS count FROM students")[0]["count"]
            == count
        )
        assert (
            instance.query("SELECT COUNT(*) AS count FROM evaluations")[0]["count"] == 0
        )
        assert (
            instance.query("SELECT COUNT(*) AS count FROM student_exercises")[0][
                "count"
            ]
            == 0
        )
        with ThreadPoolExecutor(max_workers=count) as pool:
            for round_index in range(len(EXERCISES)):
                assignments = [
                    (student, journeys[student.id][round_index]) for student in students
                ]
                round_report = {
                    "round": round_index + 1,
                    "groups": dict(Counter(exercise for _, exercise in assignments)),
                    "submissions": [],
                }
                report["rounds"].append(round_report)
                remaining = assignments
                for attempt in (1, 2, 3):
                    if not remaining:
                        break
                    # Complete the whole launch wave before any evaluator stops a workspace.
                    launched = list(pool.map(lambda pair: _start(*pair), remaining))
                    ports = [port for port, _ in launched]
                    assert len(ports) == len(set(ports)), (
                        "Concurrent students share an SSH port"
                    )
                    start_latencies.extend(elapsed for _, elapsed in launched)
                    containers = instance.docker_client.containers.list(
                        all=True,
                        filters={
                            "label": [
                                f"platform.instance={instance.platform_instance}",
                                "platform.kind=dev",
                            ]
                        },
                        ignore_removed=True,
                    )
                    expected_ids = {student.id for student, _ in remaining}
                    assert {
                        container.labels["platform.student_id"]
                        for container in containers
                    } == expected_ids
                    assert all(
                        container.status == "running" for container in containers
                    )
                    report["peak_running_environments"] = max(
                        report["peak_running_environments"], len(containers)
                    )
                    if attempt == 1:
                        assert len(containers) == count
                    print(
                        f"Round {round_index + 1}, submission {attempt}: {len(remaining)} active environments",
                        flush=True,
                    )

                    def submit(pair):
                        student, exercise = pair
                        return _submit(
                            instance,
                            student,
                            exercise,
                            attempt == attempts[student.id, exercise],
                        )

                    results = list(pool.map(submit, remaining))
                    for evaluation_id, elapsed in results:
                        assert evaluation_id not in evaluation_ids
                        evaluation_ids.add(evaluation_id)
                        grade_latencies.append(elapsed)
                    passed = sum(
                        attempt == attempts[student.id, exercise]
                        for student, exercise in remaining
                    )
                    round_report["submissions"].append(
                        {
                            "attempt": attempt,
                            "submitted": len(remaining),
                            "passed": passed,
                        }
                    )
                    remaining = [
                        (student, exercise)
                        for student, exercise in remaining
                        if attempt < attempts[student.id, exercise]
                    ]
                assert not remaining, (
                    "Students did not finish after their third submission"
                )

            def verify(student):
                for exercise in EXERCISES:
                    detail = _json(
                        student.client.get(f"/api/v1/exercises/{exercise}"),
                        f"Detail {student.name}/{exercise}",
                    )
                    assert detail["completed"] is True
                    history = _json(
                        student.client.get(f"/api/v1/exercises/{exercise}/evaluations"),
                        f"History {student.name}/{exercise}",
                    )["evaluations"]
                    assert len(history) == attempts[student.id, exercise]
                    assert all(item["status"] == "completed" for item in history)
                    assert sum(item["percentage"] == 100.0 for item in history) == 1
                    assert history[0]["percentage"] == 100.0
                environment = _json(
                    student.client.get("/api/v1/environment"),
                    f"Environment {student.name}",
                )
                assert environment["state"] == "stopped"
                assert environment["locked"] is False

            list(pool.map(verify, students))
        expected_evaluations = sum(attempts.values())
        assert len(evaluation_ids) == expected_evaluations
        assert instance.query("SELECT COUNT(*) AS count FROM student_exercises")[0][
            "count"
        ] == count * len(EXERCISES)
        assert (
            instance.query("SELECT COUNT(*) AS count FROM evaluations")[0]["count"]
            == expected_evaluations
        )
        assert (
            instance.query("SELECT COUNT(*) AS count FROM student_runtime")[0]["count"]
            == 0
        )
        assert report["peak_running_environments"] == count
        report["status"] = "passed"
    except BaseException as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        elapsed = time.perf_counter() - started
        report["elapsed_seconds"] = round(elapsed, 3)
        report["evaluations"] = len(evaluation_ids)
        report["evaluations_per_second"] = round(len(evaluation_ids) / elapsed, 3)
        if start_latencies:
            report["start_latency"] = _latencies(start_latencies)
        if grade_latencies:
            report["grade_latency"] = _latencies(grade_latencies)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        record_property("simulation_report", str(report_path))
        record_property("simulation_students", count)
        print(json.dumps(report, indent=2), flush=True)
