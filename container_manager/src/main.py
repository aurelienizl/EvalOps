"""Load the catalog, then execute database requests one at a time."""

import asyncio
import logging
import signal
import asyncpg
from .core.config import load_settings
from .core.health import HealthState, serve_health
from .database.connection import open_connection
from .database import queries as q
from .runtime.docker import open_docker_client, close_docker_client, io_call
from .catalog.loader import load_catalog
from .runtime.recovery import reconcile_runtime
from .runtime.environments import start_environment, stop_environment
from .grading.evaluations import grade_evaluation

log = logging.getLogger(__name__)


async def run_actions(connection, client, settings, wake, stop):
    while not stop.is_set():
        # Clear BEFORE reading: notifications received during work remain pending.
        wake.clear()
        blocked = await reconcile_runtime(connection, client, settings)
        for request in await q.find_requests(connection):
            if stop.is_set():
                return
            if request["user_id"] in blocked:
                continue
            try:
                if request["status"] == "grading":
                    evaluation = await q.get_evaluation(connection, request["current_operation_id"])
                    await grade_evaluation(connection, client, settings, evaluation)
                else:
                    action = (
                        start_environment if request["status"] == "starting" else stop_environment
                    )
                    await action(connection, client, settings, request)
            except (asyncpg.PostgresError, asyncpg.InterfaceError, ConnectionError):
                raise  # Restart with a fresh connection and reconcile persisted state.
            except Exception:
                log.exception("action_failed user=%s", request["user_id"])
        try:
            await asyncio.wait_for(wake.wait(), settings.poll_interval_seconds)
        except asyncio.TimeoutError:
            pass  # Also scan for lost notifications, expired containers and pending cleanup.


async def main():
    settings = load_settings()
    wake, stop = asyncio.Event(), asyncio.Event()
    health = HealthState()

    def stop_manager():
        health.ready = False
        stop.set()
        wake.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop_manager)
    connection = client = action_task = health_task = None
    try:
        connection = await open_connection(settings, wake)
        client = await io_call(open_docker_client, settings)
        settings.data_root.mkdir(parents=True, exist_ok=True)
        health_task = asyncio.create_task(serve_health(settings, health, stop))
        await load_catalog(connection, client, settings)
        await reconcile_runtime(connection, client, settings)
        health.ready = not stop.is_set()
        action_task = asyncio.create_task(run_actions(connection, client, settings, wake, stop))
        # The only other task serves HTTP health probes; it never executes actions.
        done, _ = await asyncio.wait(
            [action_task, health_task], return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            await task
    finally:
        stop_manager()
        if action_task:
            action_task.cancel()
            await asyncio.gather(action_task, return_exceptions=True)
        if health_task:
            await asyncio.gather(health_task, return_exceptions=True)
        if client:
            await io_call(close_docker_client, client)
        if connection:
            await connection.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    asyncio.run(main())
