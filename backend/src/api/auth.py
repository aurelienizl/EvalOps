"""Login and database-backed sessions."""

import asyncio
import secrets
from datetime import timedelta
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from ..core.security import (
    verify_password,
    token_hash,
    _dummy_hash,
)
from .dependencies import Database, Config, User

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=1024)


@router.post("/login")
async def login(data: LoginRequest, pool: Database, settings: Config):
    email = data.email.strip().lower()
    row = await pool.fetchrow("SELECT * FROM users WHERE lower(email)=$1", email)
    valid = await asyncio.to_thread(
        verify_password, data.password, row["password_hash"] if row else _dummy_hash
    )
    if row is None or not valid:
        raise HTTPException(401, "Invalid email or password")
    token = secrets.token_urlsafe(32)
    async with pool.acquire() as c, c.transaction():
        # Serialize session creation with password changes, preventing stale login.
        current = await c.fetchrow(
            "SELECT password_hash FROM users WHERE id=$1 FOR UPDATE", row["id"]
        )
        if current["password_hash"] != row["password_hash"]:
            raise HTTPException(401, "Credentials changed; sign in again")
        await c.execute("DELETE FROM sessions WHERE expires_at<=now() AND user_id=$1", row["id"])
        await c.execute(
            """INSERT INTO sessions(user_id,token_hash,expires_at)
            VALUES($1,$2,now()+$3::interval)""",
            row["id"],
            token_hash(token),
            timedelta(seconds=settings.session_ttl_seconds),
        )
    user = dict(
        id=row["id"],
        email=row["email"],
        role=row["role"],
        avatar=row["avatar"],
        has_ssh_key=bool(row["ssh_key"]),
    )
    response = JSONResponse(jsonable_encoder(dict(user=user)))
    response.set_cookie(
        settings.cookie_name,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.secure_cookie,
        samesite="strict",
        path="/",
    )
    return response


@router.post("/logout", status_code=204)
async def logout(request: Request, pool: Database, settings: Config, user: User):
    await pool.execute(
        "DELETE FROM sessions WHERE token_hash=$1 AND user_id=$2",
        token_hash(request.cookies.get(settings.cookie_name, "")),
        user.id,
    )
    response = Response(status_code=204)
    response.delete_cookie(
        settings.cookie_name,
        path="/",
        secure=settings.secure_cookie,
        httponly=True,
        samesite="strict",
    )
    return response


@router.get("/me")
async def me(user: User):
    return dict(user=user.public())
