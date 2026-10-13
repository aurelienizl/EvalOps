"""Unit tests for backend administration CLI."""

import argparse
from unittest.mock import Mock
import pytest

import backend.src.cli as cli
from backend.src.db import connect_db, init_db


@pytest.mark.parametrize("handler", [cli.handle_create_user, cli.handle_reset_password])
@pytest.mark.parametrize("passwords, expected_error", [
    (["short", "different"], "ne correspondent pas"),
    (["short", "short"], "au moins 8 caractères"),
])
def test_cli_rejects_invalid_passwords(tmp_db, monkeypatch, capsys, handler, passwords, expected_error):
    """CLI rejects mismatching or short passwords (< 8 chars) without modifying DB."""
    monkeypatch.setattr(cli.getpass, "getpass", Mock(side_effect=passwords))
    email = "new@ecole.fr" if handler is cli.handle_create_user else "alice@ecole.fr"

    with pytest.raises(SystemExit) as exc:
        handler(argparse.Namespace(email=email, role="student"))

    assert exc.value.code == 1
    assert expected_error in capsys.readouterr().err

    with connect_db(tmp_db) as conn:
        # Original students count and Alice's password remain untouched
        assert conn.execute("SELECT count(*) FROM students").fetchone()[0] == 2


def test_cli_create_user(tmp_db, monkeypatch):
    """create-user successfully creates a student with hashed password."""
    monkeypatch.setattr(cli.getpass, "getpass", Mock(side_effect=["SecretPass123!", "SecretPass123!"]))
    monkeypatch.setattr(cli.sys, "argv", ["evalops", "create-user", "--email", "charlie@ecole.fr"])

    cli.main()

    with connect_db(tmp_db) as conn:
        row = conn.execute("SELECT email, password_hash FROM students WHERE email = 'charlie@ecole.fr'").fetchone()
        assert row is not None
        assert row[0] == "charlie@ecole.fr"
        assert row[1] != "SecretPass123!"


def test_cli_reset_password_revokes_sessions(tmp_db, monkeypatch):
    """reset-password updates password and immediately revokes all active student sessions."""
    # Insert active session for Alice
    with connect_db(tmp_db) as conn:
        conn.execute("INSERT INTO sessions VALUES ('alice-token', 'student-a-id', 'csrf-token', '2999-01-01')")

    monkeypatch.setattr(cli.getpass, "getpass", Mock(side_effect=["NewPassword999!", "NewPassword999!"]))
    monkeypatch.setattr(cli.sys, "argv", ["evalops", "reset-password", "--email", "alice@ecole.fr"])

    cli.main()

    with connect_db(tmp_db) as conn:
        # Password updated
        student = conn.execute("SELECT password_hash FROM students WHERE email = 'alice@ecole.fr'").fetchone()
        assert student is not None
        # Sessions revoked
        session_count = conn.execute("SELECT count(*) FROM sessions WHERE student_id = 'student-a-id'").fetchone()[0]
        assert session_count == 0


def test_cli_init_db(tmp_path, monkeypatch):
    """init-db creates database schema without errors."""
    fresh_db = tmp_path / "fresh.db"
    monkeypatch.setenv("DATABASE_PATH", str(fresh_db))
    monkeypatch.setattr(cli.sys, "argv", ["evalops", "init-db"])

    cli.main()

    with connect_db(fresh_db) as conn:
        assert conn.execute("SELECT count(*) FROM students").fetchone()[0] == 0


def test_cli_create_admin_and_manage_roles(tmp_db, monkeypatch, capsys):
    """create-user with --role admin, list-users, and set-role work correctly."""
    # 1. Create admin user
    monkeypatch.setattr(cli.getpass, "getpass", Mock(side_effect=["AdminPass123!", "AdminPass123!"]))
    monkeypatch.setattr(cli.sys, "argv", ["evalops", "create-user", "--email", "prof@ecole.fr", "--role", "admin"])
    cli.main()

    with connect_db(tmp_db) as conn:
        prof = conn.execute("SELECT role FROM students WHERE email = 'prof@ecole.fr'").fetchone()
        assert prof is not None
        assert prof["role"] == "admin"

    # 2. List users
    monkeypatch.setattr(cli.sys, "argv", ["evalops", "list-users"])
    cli.main()
    out = capsys.readouterr().out
    assert "prof@ecole.fr" in out
    assert "[ADMIN]" in out

    # 3. Change role
    monkeypatch.setattr(cli.sys, "argv", ["evalops", "set-role", "--email", "alice@ecole.fr", "--role", "admin"])
    cli.main()
    with connect_db(tmp_db) as conn:
        alice = conn.execute("SELECT role FROM students WHERE email = 'alice@ecole.fr'").fetchone()
        assert alice["role"] == "admin"

