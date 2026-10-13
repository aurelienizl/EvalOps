"""Authentication, session security, password hashing, and SSH key validation."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Tuple

from argon2 import PasswordHasher
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import load_ssh_public_key

ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64 MB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return ph.verify(password_hash, password)
    except Exception:
        return False


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_session_credentials() -> Tuple[str, str, str, str]:
    """Generates (raw_token, token_hash, csrf_token, expires_at_iso)."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_session_token(raw_token)
    csrf_token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
    return raw_token, token_hash, csrf_token, expires_at


class SSHKeyValidationError(Exception):
    pass


def validate_and_normalize_ed25519_key(key_text: str) -> str:
    """
    Validates and normalizes an OpenSSH ed25519 public key.
    Only allows the raw key itself (ssh-ed25519 <key_data>).
    Rejects comments, options, private keys, other key types, multiple lines, and malformed keys.
    """
    if not key_text:
        raise SSHKeyValidationError("La clé SSH ne peut pas être vide")

    cleaned = key_text.strip()
    if "\n" in cleaned or "\r" in cleaned:
        raise SSHKeyValidationError("La clé SSH ne doit comporter qu'une seule ligne")

    parts = cleaned.split()
    if len(parts) < 2:
        raise SSHKeyValidationError("Format de clé SSH invalide")
    if len(parts) > 2:
        raise SSHKeyValidationError("Les commentaires et options ne sont pas autorisés : seule la clé brute doit être fournie")

    if parts[0] != "ssh-ed25519":
        raise SSHKeyValidationError("Seules les clés ssh-ed25519 sont acceptées")

    try:
        key_bytes = f"{parts[0]} {parts[1]}".encode("ascii")
        public_key = load_ssh_public_key(key_bytes)
    except Exception as e:
        raise SSHKeyValidationError(f"Clé SSH invalide ou corrompue: {e}")

    if not isinstance(public_key, ed25519.Ed25519PublicKey):
        raise SSHKeyValidationError("La clé fournie n'est pas une clé Ed25519 valide")

    return f"{parts[0]} {parts[1]}"
