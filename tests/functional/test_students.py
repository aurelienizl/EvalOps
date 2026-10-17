"""Five students use the real API, SSH, compiler, grader and saved workspaces."""

from concurrent.futures import ThreadPoolExecutor
from tests.tools.users import HELLO, SUM


def test_five_students_work_on_two_exercises(deployment, users):
    assert int(deployment.config["services"]["backend"]["environment"]["MAX_ENVIRONMENTS"]) >= 5
    students = [users() for _ in range(5)]
    with ThreadPoolExecutor(max_workers=5) as executor:
        shells = list(executor.map(lambda student: student.start(), students))
        ports = [shell.connection["port"] for shell in shells]
        assert len(set(ports)) == 5
        assert len(deployment.containers(kind="development")) == 5

        def first_attempt(index):
            student, ssh = students[index], shells[index]
            output = "Hello C" if index % 2 == 0 else "incorrect"
            source = f'#include <stdio.h>\n#include <unistd.h>\nint main(void){{sleep(1);puts("{output}");}}\n'
            ssh.write("hello-c/main.c", source)
            ssh.write("hello-c/student.txt", student.email)
            assert ssh.run("id -u").strip() == "1000"
            ssh.run("cd hello-c && gcc -Wall -Wextra main.c -o app && ./app")
            evaluation_id = student.submit()
            state = student.state()
            assert state["locked"] and state["environment"]["ssh"] is None
            student.api.post("/environment/stop", expected=409)
            student.api.post("/exercises/sum-c/start", expected=409)
            assert len(deployment.containers(kind="evaluator")) <= 1
            report = student.report(evaluation_id)
            assert report["status"] == "completed" and report["is_success"] == (index % 2 == 0)
            snapshot = student.snapshot(evaluation_id)
            assert snapshot["workspace/main.c"] == source.encode()
            assert snapshot["workspace/student.txt"] == student.email.encode()

        list(executor.map(first_attempt, range(5)))

        def finish(student):
            ssh = student.start()
            assert ssh.run("cat hello-c/student.txt") == student.email
            ssh.write("hello-c/main.c", HELLO)
            assert student.report(student.submit())["is_success"]
            assert student.api.get("/exercises/hello-c").json()["is_completed"]
            ssh = student.start("sum-c")
            ssh.write("sum-c/sum.c", SUM)
            assert (
                ssh.run(
                    "cd sum-c && gcc -Wall -Wextra sum.c -o sum && printf '2 3\\n' | ./sum"
                ).strip()
                == "5"
            )
            report = student.report(student.submit("sum-c"))
            assert report["status"] == "completed" and report["is_success"]
            assert student.api.get("/exercises/sum-c").json()["is_completed"]

        list(executor.map(finish, students))
    assert not deployment.containers()
