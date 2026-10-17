"""Public key validation and password rotation."""

import asyncio
import base64
import hashlib
from cryptography.hazmat.primitives.serialization import load_ssh_public_key, Encoding, PublicFormat
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from ..core.security import verify_password, hash_password
from ..database.connection import transaction, lock_student
from .common import active_evaluation
from .dependencies import Database, Config, User


router = APIRouter(prefix="/profile", tags=["Profile"])


class SSHKeyRequest(BaseModel):
    public_key: str = Field(min_length=1, max_length=8192)


class PasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


@router.put("/ssh-key")
async def update_ssh_key(data: SSHKeyRequest, pool: Database, user: User):
    value = data.public_key.strip()
    if "\n" in value or not value.startswith(("ssh-ed25519 ", "ssh-rsa ")):
        raise HTTPException(400, "Expected one OpenSSH Ed25519/RSA public key")
    try:
        key = load_ssh_public_key(value.encode())
        if (
            not isinstance(key, (ed25519.Ed25519PublicKey, rsa.RSAPublicKey))
            or isinstance(key, rsa.RSAPublicKey)
            and key.key_size < 3072
        ):
            raise ValueError("Unsupported key")
        normalized = key.public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, "Invalid public key; RSA must have at least 3072 bits") from exc
    async with transaction(pool) as c:
        await lock_student(c, user.id)
        env = await c.fetchrow("SELECT * FROM environments WHERE user_id=$1 FOR UPDATE", user.id)
        if (
            await active_evaluation(c, user.id)
            or env
            and (env["status"] != "stopped" or env["container_id"] or env["ssh_port"])
        ):
            raise HTTPException(409, "Stop the environment before replacing its key")
        await c.execute("UPDATE users SET ssh_key=$1 WHERE id=$2", normalized, user.id)
    blob = base64.b64decode(normalized.split()[1])
    return dict(
        fingerprint="SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    )


@router.put("/password", status_code=204)
async def update_password(data: PasswordRequest, pool: Database, settings: Config, user: User):
    old = await pool.fetchval("SELECT password_hash FROM users WHERE id=$1", user.id)
    if not await asyncio.to_thread(verify_password, data.current_password, old):
        raise HTTPException(403, "Current password is incorrect")
    encoded = await asyncio.to_thread(hash_password, data.new_password)
    async with transaction(pool) as c:
        await lock_student(c, user.id)
        if await c.fetchval("SELECT password_hash FROM users WHERE id=$1", user.id) != old:
            raise HTTPException(409, "Credentials changed; retry after signing in")
        await c.execute("UPDATE users SET password_hash=$1 WHERE id=$2", encoded, user.id)
        await c.execute("DELETE FROM sessions WHERE user_id=$1", user.id)
    response = Response(status_code=204)
    response.delete_cookie(
        settings.cookie_name,
        path="/",
        secure=settings.secure_cookie,
        httponly=True,
        samesite="strict",
    )
    return response
