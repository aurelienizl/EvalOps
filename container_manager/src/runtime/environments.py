"""Start and stop actions, called sequentially by the manager."""

import logging
from docker.errors import NotFound
from ..database import queries as q
from ..database.connection import transaction, lock_student_row
from . import docker as d
from .workspaces import prepare_development_workspace

log = logging.getLogger(__name__)


async def remove_development(client, settings, user_id, env):
    owned = await d.list_managed_containers(client, settings, user_id)
    devs = [item for item in owned if item.kind == "development"]
    if env and env["container_id"] and env["container_id"] not in {item.id for item in devs}:
        try:
            await d.io_call(client.containers.get, env["container_id"])
        except NotFound:
            pass
        else:
            raise RuntimeError("Tracked container ownership cannot be confirmed")
    for item in devs:
        await d.stop_and_remove_container(client, item.id, settings.stop_grace_seconds)


async def start_environment(connection, client, settings, request):
    env = await q.get_environment(connection, request["user_id"])
    if (
        not env
        or env["status"] != "starting"
        or env["current_operation_id"] != request["current_operation_id"]
    ):
        return
    try:
        active = await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM evaluations WHERE user_id=$1 AND status='running' AND finished_at IS NULL)",
            env["user_id"],
        )
        if active:
            return
        owned = await d.list_managed_containers(client, settings, env["user_id"])
        for item in owned:
            if item.operation_id != env["current_operation_id"] or item.kind != "development":
                await d.stop_and_remove_container(client, item.id, settings.stop_grace_seconds)
        ex = dict(await q.get_exercise(connection, env["exercise_id"]))
        ex["resources"] = await connection.fetch(
            "SELECT file_path FROM exercise_resources WHERE exercise_id=$1", ex["id"]
        )
        key = await q.get_ssh_key(connection, env["user_id"])
        if not key:
            raise ValueError("SSH key missing")
        workspace = await d.io_call(
            prepare_development_workspace, settings, env["user_id"], ex, key
        )
        container = await d.create_development_container(
            client,
            settings,
            env["user_id"],
            ex["id"],
            env["current_operation_id"],
            ex["environment_image"],
            workspace.directory,
            ex["workspace_dir"],
            workspace.authorized_key,
        )
        async with transaction(connection):
            await lock_student_row(connection, env["user_id"])
            saved = await q.mark_environment_running(
                connection,
                env["user_id"],
                env["current_operation_id"],
                container.id,
                container.ssh_port,
                settings.environment_ttl_seconds,
            )
        if not saved:
            await d.stop_and_remove_container(client, container.id, settings.stop_grace_seconds)
    except BaseException:
        try:
            await remove_development(client, settings, env["user_id"], env)
            async with transaction(connection):
                await lock_student_row(connection, env["user_id"])
                await q.mark_environment_stopped(
                    connection, env["user_id"], env["current_operation_id"], "starting"
                )
        except Exception:
            log.error("start_cleanup_pending user=%s", env["user_id"])
        raise


async def stop_environment(connection, client, settings, request):
    env = await q.get_environment(connection, request["user_id"])
    if (
        not env
        or env["status"] != "stopping"
        or env["current_operation_id"] != request["current_operation_id"]
    ):
        return
    await remove_development(client, settings, env["user_id"], env)
    async with transaction(connection):
        await lock_student_row(connection, env["user_id"])
        await q.mark_environment_stopped(
            connection, env["user_id"], env["current_operation_id"], "stopping"
        )


async def stop_development_for_grading(connection, client, settings, evaluation):
    env = await q.get_environment(connection, evaluation["user_id"])
    if not env or env["status"] != "grading" or env["current_operation_id"] != evaluation["id"]:
        raise RuntimeError("Stale grading reservation")
    await remove_development(client, settings, evaluation["user_id"], env)
    async with transaction(connection):
        await lock_student_row(connection, evaluation["user_id"])
        if not await q.clear_development_container(
            connection, evaluation["user_id"], evaluation["id"], "grading"
        ):
            raise RuntimeError("Lost grading reservation")
