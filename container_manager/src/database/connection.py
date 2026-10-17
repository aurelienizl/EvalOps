"""One PostgreSQL connection for SQL, notifications and the instance guard."""

from contextlib import asynccontextmanager
import asyncpg


async def open_connection(settings, wake):
    connection = await asyncpg.connect(settings.database_url, command_timeout=15)
    try:
        if not await connection.fetchval("SELECT pg_try_advisory_lock(62001)"):
            raise RuntimeError("Another Container Manager is already connected")
        for channel in ("environment_events", "grade_queue"):
            await connection.add_listener(channel, lambda *args: wake.set())
        return connection
    except BaseException:
        await connection.close()
        raise


@asynccontextmanager
async def transaction(connection):
    async with connection.transaction():
        await connection.execute("SET LOCAL lock_timeout='5s'")
        yield


async def lock_student_row(connection, user_id):
    if not await connection.fetchval("SELECT id FROM users WHERE id=$1 FOR UPDATE", user_id):
        raise ValueError("Unknown user")
