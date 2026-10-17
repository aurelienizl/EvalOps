"""SQL setup and manager requests through the existing PostgreSQL container."""

import json
from uuid import uuid4
from .wait import eventually


def quote(value):
    return "NULL" if value is None else "'" + str(value).replace("'", "''") + "'"


class Database:
    def __init__(self, deployment):
        self.deployment = deployment
        self.settings = deployment.config["services"]["db"]["environment"]

    def execute(self, sql):
        return self.deployment.compose(
            "exec",
            "-T",
            "db",
            "psql",
            "-X",
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            self.settings["POSTGRES_USER"],
            "-d",
            self.settings["POSTGRES_DB"],
            input=sql,
        ).stdout.strip()

    def rows(self, sql):
        return json.loads(self.execute(f"SELECT coalesce(json_agg(r), '[]'::json) FROM ({sql}) r;"))

    def environment(self, user_id):
        rows = self.rows(f"SELECT * FROM environments WHERE user_id={quote(user_id)}")
        return rows[0] if rows else None

    def wait_environment(self, user_id, status):
        def ready():
            env = self.environment(user_id)
            return env if env and env["status"] == status else None

        return eventually(ready, description=f"environment {user_id}: {status}")

    def start(self, user_id, exercise="hello-c", *, notify=True):
        self.execute(f"""BEGIN;
            INSERT INTO environments(user_id,exercise_id,status,current_operation_id)
            VALUES({quote(user_id)},{quote(exercise)},'starting',{quote(uuid4())})
            ON CONFLICT(user_id) DO UPDATE SET exercise_id=EXCLUDED.exercise_id,
            status='starting',current_operation_id=EXCLUDED.current_operation_id;
            {"NOTIFY environment_events;" if notify else ""}
            COMMIT;""")
        return self.wait_environment(user_id, "running")

    def stop(self, user_id):
        self.execute(f"""BEGIN;
            UPDATE environments SET status='stopping',current_operation_id={quote(uuid4())}
            WHERE user_id={quote(user_id)};
            NOTIFY environment_events; COMMIT;""")
        return self.wait_environment(user_id, "stopped")

    def grade(self, user_id, exercise="hello-c"):
        evaluation_id = str(uuid4())
        self.execute(f"""BEGIN;
            INSERT INTO evaluations(id,user_id,exercise_id,status)
            VALUES({quote(evaluation_id)},{quote(user_id)},{quote(exercise)},'running');
            UPDATE environments SET status='grading',current_operation_id={quote(evaluation_id)}
            WHERE user_id={quote(user_id)};
            NOTIFY grade_queue; COMMIT;""")
        return evaluation_id

    def wait_report(self, evaluation_id):
        def finished():
            report = self.rows(f"SELECT * FROM evaluations WHERE id={quote(evaluation_id)}")[0]
            return report if report["finished_at"] else None

        return eventually(finished, timeout=180, description=f"evaluation {evaluation_id}")
