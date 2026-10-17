"""Server-side sessions, Argon2id passwords and role checks."""

from dataclasses import dataclass, asdict
from uuid import UUID
import hashlib
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import HTTPException, Request
from .config import Settings

_hasher = PasswordHasher()
_dummy_hash = _hasher.hash("dummy-login-verification")


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    email: str
    role: str
    avatar: str | None
    has_ssh_key: bool

    def public(self) -> dict:
        return asdict(self)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def require_user(request: Request, pool, settings: Settings) -> CurrentUser:
    token = request.cookies.get(settings.cookie_name, "")
    if not token or len(token) > 256:
        raise HTTPException(401, "Authentication required")
    row = await pool.fetchrow(
        """SELECT u.id,u.email,u.role,u.avatar,u.ssh_key IS NOT NULL AS has_ssh_key
        FROM sessions s JOIN users u ON u.id=s.user_id
        WHERE s.token_hash=$1 AND s.expires_at>now()""",
        token_hash(token),
    )
    if row is None:
        raise HTTPException(401, "Session expired")
    return CurrentUser(**dict(row))


def require_admin(user: CurrentUser) -> None:
    if user.role != "admin":
        raise HTTPException(403, "Administrator access required")
