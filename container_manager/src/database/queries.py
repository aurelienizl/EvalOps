"""Manager SQL using only columns and statuses in db/schema.sql."""


async def find_requests(connection):
    return await connection.fetch(
        """SELECT * FROM environments e WHERE status IN ('starting','stopping')
        OR (status='grading' AND EXISTS(SELECT 1 FROM evaluations v
            WHERE v.id=e.current_operation_id AND v.user_id=e.user_id
            AND v.status='running' AND v.finished_at IS NULL))
        ORDER BY last_activity_at,user_id"""
    )


async def find_recovery_students(connection):
    return [
        r["user_id"]
        for r in await connection.fetch(
            """SELECT user_id FROM environments WHERE status<>'stopped'
            OR container_id IS NOT NULL OR ssh_port IS NOT NULL OR current_operation_id IS NOT NULL
            UNION SELECT user_id FROM evaluations WHERE finished_at IS NULL"""
        )
    ]


async def get_environment(connection, user_id):
    return await connection.fetchrow("SELECT * FROM environments WHERE user_id=$1", user_id)


async def get_evaluation(connection, evaluation_id):
    return await connection.fetchrow("SELECT * FROM evaluations WHERE id=$1", evaluation_id)


async def get_exercise(connection, exercise_id):
    row = await connection.fetchrow("SELECT * FROM exercises WHERE id=$1", exercise_id)
    if row is None:
        raise ValueError("Unknown exercise")
    return row


async def get_ssh_key(connection, user_id):
    return await connection.fetchval("SELECT ssh_key FROM users WHERE id=$1", user_id)


async def mark_environment_running(
    connection, user_id, operation_id, container_id, ssh_port, ttl_seconds=7200
):
    result = await connection.execute(
        """UPDATE environments SET status='running',container_id=$3,ssh_port=$4,
        last_activity_at=now(),expires_at=now()+make_interval(secs=>$5)
        WHERE user_id=$1 AND current_operation_id=$2 AND status='starting'""",
        user_id,
        operation_id,
        container_id,
        ssh_port,
        float(ttl_seconds),
    )
    return result == "UPDATE 1"


async def clear_development_container(connection, user_id, operation_id, expected_status):
    result = await connection.execute(
        """UPDATE environments SET container_id=NULL,ssh_port=NULL
        WHERE user_id=$1 AND current_operation_id=$2 AND status=$3""",
        user_id,
        operation_id,
        expected_status,
    )
    return result == "UPDATE 1"


async def mark_environment_stopped(connection, user_id, operation_id, expected_status):
    result = await connection.execute(
        """UPDATE environments SET status='stopped',container_id=NULL,ssh_port=NULL,
        expires_at=NULL,current_operation_id=NULL,last_activity_at=now()
        WHERE user_id=$1 AND current_operation_id IS NOT DISTINCT FROM $2::uuid AND status=$3
        AND NOT EXISTS(SELECT 1 FROM evaluations WHERE user_id=$1 AND finished_at IS NULL AND status='running')""",
        user_id,
        operation_id,
        expected_status,
    )
    return result == "UPDATE 1"


async def finalize_evaluation(
    connection,
    evaluation,
    status,
    report,
    cleanup_state,
    error_code=None,
    error_message=None,
    snapshot_archive_path=None,
):
    from .connection import transaction, lock_student_row

    async with transaction(connection):
        await lock_student_row(connection, evaluation["user_id"])
        env = await connection.fetchrow(
            "SELECT * FROM environments WHERE user_id=$1 FOR UPDATE", evaluation["user_id"]
        )
        current = await connection.fetchrow(
            "SELECT * FROM evaluations WHERE id=$1 FOR UPDATE", evaluation["id"]
        )
        if (
            not env
            or env["current_operation_id"] != evaluation["id"]
            or not current
            or current["finished_at"] is not None
        ):
            return False
        if status == "completed" and report is None:
            raise ValueError("Completed evaluation requires a report")
        success = status == "completed" and report.is_success
        if report:
            await connection.executemany(
                """INSERT INTO evaluation_tests(evaluation_id,name,status,return_code,stdout_diff,stderr_diff,execution_time_ms)
                VALUES($1,$2,$3,$4,$5,$6,$7)""",
                [
                    (
                        evaluation["id"],
                        t.name,
                        t.status,
                        t.return_code,
                        t.stdout_diff,
                        t.stderr_diff or t.message,
                        t.execution_time_ms,
                    )
                    for t in report.tests
                ],
            )
        await connection.execute(
            """UPDATE evaluations SET status=$2,is_success=$3,passed_tests=$4,total_tests=$5,
            error_code=$6,error_message=$7,snapshot_archive_path=$8,finished_at=now() WHERE id=$1""",
            evaluation["id"],
            status,
            bool(success),
            report.passed_tests if report else 0,
            report.total_tests if report else 0,
            error_code,
            error_message,
            snapshot_archive_path,
        )
        if success:
            await connection.execute(
                """INSERT INTO user_completed_exercises(user_id,exercise_id,successful_evaluation_id)
                VALUES($1,$2,$3) ON CONFLICT(user_id,exercise_id) DO NOTHING""",
                evaluation["user_id"],
                evaluation["exercise_id"],
                evaluation["id"],
            )
        if cleanup_state == "stopped":
            await mark_environment_stopped(
                connection, evaluation["user_id"], evaluation["id"], env["status"]
            )
        else:
            await connection.execute(
                "UPDATE environments SET status=$2 WHERE user_id=$1",
                evaluation["user_id"],
                cleanup_state,
            )
        return True
