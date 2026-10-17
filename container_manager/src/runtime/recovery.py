"""Reconcile containers and expire development environments between action batches."""

import logging
from datetime import datetime, timezone
from uuid import uuid4
import asyncpg
from ..database import queries as q
from ..database.connection import transaction, lock_student_row
from . import docker as d
from .environments import remove_development

log = logging.getLogger(__name__)


async def reconcile_runtime(connection, client, settings):
    blocked = set()
    owned = await d.list_managed_containers(client, settings)
    users = set(await q.find_recovery_students(connection)) | {item.user_id for item in owned}
    for user_id in users:
        try:
            env = await q.get_environment(connection, user_id)
            containers = [item for item in owned if item.user_id == user_id]
            evaluators = [item for item in containers if item.kind == "evaluator"]
            # No grading action can be executing while this serial check runs.
            for item in evaluators:
                await d.stop_and_remove_container(client, item.id, settings.stop_grace_seconds)
            if env is None:
                for item in containers:
                    if item.kind == "development":
                        await d.stop_and_remove_container(
                            client, item.id, settings.stop_grace_seconds
                        )
                continue
            job = (
                await q.get_evaluation(connection, env["current_operation_id"])
                if env["current_operation_id"]
                else None
            )
            if job and job["finished_at"] is None:
                if evaluators:
                    await remove_development(client, settings, user_id, env)
                    await q.finalize_evaluation(
                        connection,
                        job,
                        "failed",
                        None,
                        "stopped",
                        "worker_interrupted",
                        "Evaluation interrupted; submit again",
                    )
                # Without an evaluator, this is a queued request: execute it normally.
                continue
            if env["status"] in ("grading", "stopped"):
                await remove_development(client, settings, user_id, env)
                async with transaction(connection):
                    await lock_student_row(connection, user_id)
                    await q.mark_environment_stopped(
                        connection, user_id, env["current_operation_id"], env["status"]
                    )
            elif env["status"] == "running":
                matching = any(
                    item.kind == "development" and item.id == env["container_id"] and item.running
                    for item in containers
                )
                expired = env["expires_at"] is not None and env["expires_at"] <= datetime.now(
                    timezone.utc
                )
                if not matching or expired:
                    async with transaction(connection):
                        await lock_student_row(connection, user_id)
                        await connection.execute(
                            """UPDATE environments SET status='stopping',current_operation_id=$2
                            WHERE user_id=$1 AND status='running'
                            AND current_operation_id IS NOT DISTINCT FROM $3::uuid""",
                            user_id,
                            uuid4(),
                            env["current_operation_id"],
                        )
                for item in containers:
                    if item.kind == "development" and item.id != env["container_id"]:
                        await d.stop_and_remove_container(
                            client, item.id, settings.stop_grace_seconds
                        )
            # starting/stopping are commands for the action loop.
        except (asyncpg.PostgresError, asyncpg.InterfaceError, ConnectionError):
            raise
        except Exception:
            # Leave this student's controls locked and retry cleanup next time.
            blocked.add(user_id)
            log.exception("cleanup_pending user=%s", user_id)
    return blocked
