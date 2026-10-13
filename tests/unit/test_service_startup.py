"""Synchronous startup, readiness and service cleanup regressions."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import container_manager.src.app as manager_app
import backend.src.app as backend_app
from backend.src.db import connect_db
from backend.src.state import get_catalog as get_backend_catalog, get_runtime_manager
from container_manager.src.api.v1.system import get_health
from container_manager.src.services import state


@pytest.fixture
def manager_state(monkeypatch):
    for name in ("_catalog", "_build_manager", "_docker_runtime", "_startup_error"):
        monkeypatch.setattr(state, name, None)


@pytest.mark.parametrize("phase, ready, error, status", [
    (None, False, None, 503),
    ("preparing", False, None, 503),
    ("ready", True, None, 200),
    ("failed", False, "Failure", 503),
    ("ready", True, "Failure", 503),
])
def test_manager_health_requires_ready_builds(manager_state, phase, ready, error, status):
    state.set_build_manager(SimpleNamespace(phase=phase, is_ready=ready) if phase else None)
    state.set_docker_runtime(Mock())
    state.set_startup_error(error)
    assert get_health().status_code == status


def test_manager_health_checks_docker_after_startup(manager_state):
    runtime = Mock()
    runtime.client.ping.side_effect = RuntimeError("Docker offline")
    state.set_docker_runtime(runtime)
    state.set_build_manager(SimpleNamespace(phase="ready", is_ready=True))
    assert get_health().status_code == 503


def test_builds_finish_on_startup_thread_before_yield(manager_state, monkeypatch):
    client = Mock()
    runtime = Mock()
    catalog = SimpleNamespace(exercises_by_id={"ex": SimpleNamespace(
        id="ex", dev_context_path="dev", evaluator_context_path="eval",
    )})
    thread_id = threading.get_ident()
    events = []

    def build(**kwargs):
        assert threading.get_ident() == thread_id
        assert get_health().status_code == 503
        events.append(kwargs["path"])
        return SimpleNamespace(id=kwargs["path"]), []

    client.images.build.side_effect = build
    monkeypatch.setattr(manager_app, "parse_and_validate_catalog", lambda _: catalog)
    monkeypatch.setattr(manager_app.docker, "from_env", lambda: client)
    monkeypatch.setattr(manager_app, "DockerRuntime", lambda **_: runtime)

    async def run():
        async with manager_app.lifespan(manager_app.app):
            assert events == ["dev", "eval"]
            assert get_health().status_code == 200
            client.close.assert_not_called()
        assert get_health().status_code == 503

    asyncio.run(run())
    runtime.cleanup_on_startup.assert_called_once()
    client.ping.assert_called_once()
    client.close.assert_called_once()


@pytest.mark.parametrize("failure", ["ping", "cleanup", "build"])
def test_manager_startup_failure_closes_client_and_aborts(manager_state, monkeypatch, failure):
    client = Mock()
    runtime = Mock()
    builder = SimpleNamespace(phase="preparing", is_ready=False, run_all_builds=Mock())
    {"ping": client.ping, "cleanup": runtime.cleanup_on_startup, "build": builder.run_all_builds}[
        failure
    ].side_effect = RuntimeError("Startup failed")
    monkeypatch.setattr(manager_app, "parse_and_validate_catalog", lambda _: object())
    monkeypatch.setattr(manager_app.docker, "from_env", lambda: client)
    monkeypatch.setattr(manager_app, "DockerRuntime", lambda **_: runtime)
    monkeypatch.setattr(manager_app, "BuildManager", lambda *_: builder)

    async def run():
        async with manager_app.lifespan(manager_app.app):
            pytest.fail("Startup failure must prevent serving requests")

    with pytest.raises(RuntimeError, match="Startup failed"):
        asyncio.run(run())
    assert get_health().status_code == 503
    client.close.assert_called_once()


def test_backend_shutdown_closes_client_and_clears_state(monkeypatch):
    manager = Mock()
    catalog = SimpleNamespace(catalog_hash="hash")
    monkeypatch.setattr(backend_app, "init_db", lambda: None)
    monkeypatch.setattr(backend_app, "parse_and_validate_catalog", lambda _: catalog)
    monkeypatch.setattr(backend_app, "RuntimeManager", lambda _: manager)

    async def run():
        async with backend_app.lifespan(backend_app.app):
            assert get_runtime_manager() is manager
            assert get_backend_catalog() is catalog
            manager.close.assert_not_called()
        assert get_runtime_manager() is None
        assert get_backend_catalog() is None

    asyncio.run(run())
    manager.close.assert_called_once()


def test_database_context_closes_and_rolls_back(tmp_db):
    import sqlite3

    with pytest.raises(RuntimeError):
        with connect_db(tmp_db) as connection:
            connection.execute("BEGIN")
            connection.execute("UPDATE students SET email = 'changed@example.com' WHERE id = 'student-a-id'")
            raise RuntimeError("abort")
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")
    with connect_db(tmp_db) as connection:
        assert connection.execute("SELECT email FROM students WHERE id = 'student-a-id'").fetchone()[0] == "alice@ecole.fr"
