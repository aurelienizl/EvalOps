"""Unit tests for authentication and SSH key validation."""

import pytest

from backend.src.core.security import (
    SSHKeyValidationError,
    hash_password,
    validate_and_normalize_ed25519_key,
    verify_password,
)


def test_password_hash_and_verify():
    """Argon2id password hashing produces non-plaintext and verifies correctly."""
    pwd = "CorrectHorseBatteryStaple123!"
    h = hash_password(pwd)
    assert h != pwd
    assert verify_password(h, pwd) is True
    assert verify_password(h, "WrongPassword") is False


def test_valid_ed25519_key(valid_ed25519_key):
    """Raw Ed25519 public key without comments or options is accepted."""
    normalized = validate_and_normalize_ed25519_key(valid_ed25519_key)
    assert normalized == valid_ed25519_key


def test_reject_key_with_comment(valid_ed25519_key):
    """SSH keys with comments (e.g. user@host) are strictly rejected."""
    key_with_comment = f"{valid_ed25519_key} student@laptop"
    with pytest.raises(SSHKeyValidationError, match="commentaires"):
        validate_and_normalize_ed25519_key(key_with_comment)


def test_reject_rsa_key():
    """Non-Ed25519 keys (such as RSA) are strictly rejected."""
    rsa_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC3"
    with pytest.raises(SSHKeyValidationError, match="Seules les clés ssh-ed25519 sont acceptées"):
        validate_and_normalize_ed25519_key(rsa_key)


def test_reject_multiline_key():
    """Multiline SSH keys are rejected."""
    key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI\nAAAAC3NzaC1lZDI1NTE5"
    with pytest.raises(SSHKeyValidationError, match="une seule ligne"):
        validate_and_normalize_ed25519_key(key)


def test_reject_options_in_key():
    """SSH keys prefixed with forced options are rejected."""
    key = 'no-pty,command="dump" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI'
    with pytest.raises(SSHKeyValidationError):
        validate_and_normalize_ed25519_key(key)


def test_reject_corrupt_key():
    """Malformed or non-base64 key material is rejected."""
    key = "ssh-ed25519 NotBase64AtAll!"
    with pytest.raises(SSHKeyValidationError):
        validate_and_normalize_ed25519_key(key)
