"""Small PostgreSQL pool and user-first transactional serialization."""

from contextlib import asynccontextmanager
from uuid import UUID
import asyncpg
from ..core.config import Settings


async def open_pool(settings: Settings) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(
        settings.database_url, min_size=1, max_size=5, command_timeout=15
    )
    try:
        await pool.fetchval("SELECT count(*) FROM courses")
    except BaseException:
        await pool.close()
        raise
    return pool


async def close_pool(pool: asyncpg.Pool) -> None:
    await pool.close()


@asynccontextmanager
async def transaction(pool: asyncpg.Pool):
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute("SET LOCAL lock_timeout='5s'")
            yield connection


async def lock_student(connection: asyncpg.Connection, user_id: UUID) -> None:
    row = await connection.fetchval("SELECT id FROM users WHERE id=$1 FOR UPDATE", user_id)
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(404, "User not found")
