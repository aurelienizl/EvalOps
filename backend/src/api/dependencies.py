"""Shared FastAPI dependencies for database access and session authentication."""

from typing import Annotated
from asyncpg import Pool
from fastapi import Depends, Query, Request
from ..core.config import Settings
from ..core.security import CurrentUser, require_user, require_admin


async def get_pool(request: Request) -> Pool:
    return request.app.state.pool


async def get_settings(request: Request) -> Settings:
    return request.app.state.settings


Database = Annotated[Pool, Depends(get_pool)]
Config = Annotated[Settings, Depends(get_settings)]


async def get_user(request: Request, pool: Database, settings: Config) -> CurrentUser:
    return await require_user(request, pool, settings)


User = Annotated[CurrentUser, Depends(get_user)]


async def get_admin(user: User) -> CurrentUser:
    require_admin(user)
    return user


Admin = Annotated[CurrentUser, Depends(get_admin)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]
