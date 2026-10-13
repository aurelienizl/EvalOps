"""Shared pytest fixtures for EvalOps tests."""

import os
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi.testclient import TestClient

import backend.src.runtime
from backend.src.app import app
from backend.src.core.security import hash_password
from backend.src.db import connect_db, create_student, init_db

TEST_STUDENT_IDS = {"student-a-id", "student-b-id", "student-test-func"}


def positive_int(value: str) -> int:
    try:
        count = int(value)
    except ValueError as exc:
        raise pytest.UsageError("Student count must be a positive integer") from exc
    if count < 1:
        raise pytest.UsageError("Student count must be a positive integer")
    return count


def pytest_addoption(parser):
    group = parser.getgroup("capacity simulation")
    group.addoption(
        "--run-capacity",
        action="store_true",
        help="Run the isolated Docker capacity simulation",
    )
    group.addoption(
        "--simulation-students",
        type=positive_int,
        default=99,
        help="Number of concurrent simulated students (default: 99)",
    )
    group.addoption(
        "--simulation-seed",
        type=int,
        default=20261013,
        help="Random seed for reproducible submission outcomes",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "capacity: isolated Docker capacity simulation (requires --run-capacity)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-capacity"):
        return
    skip = pytest.mark.skip(
        reason="Use --run-capacity to run the Docker capacity simulation"
    )
    for item in items:
        if "capacity" in item.keywords:
            item.add_marker(skip)


def get_courses_dir() -> Path:
    """Find the courses directory whether running on host or inside container."""
    env_path = os.environ.get("COURSES_PATH")
    if env_path and Path(env_path).is_dir():
        return Path(env_path)
    local_path = Path(__file__).parent.parent / "courses"
    if local_path.is_dir():
        return local_path
    if Path("/courses").is_dir():
        return Path("/courses")
    return local_path


COURSES_DIR = get_courses_dir()


def detect_container_manager_url() -> str:
    """Find the container manager URL on the dev machine."""
    url = os.environ.get("CONTAINER_MANAGER_URL")
    if url:
        return url
    try:
        if httpx.get("http://localhost:8001/v1/health", timeout=0.5).status_code == 200:
            return "http://localhost:8001"
    except Exception:
        pass
    try:
        import docker

        client = docker.from_env()
        try:
            cm = client.containers.get("evalops-container_manager-1")
            for net in cm.attrs.get("NetworkSettings", {}).get("Networks", {}).values():
                ip = net.get("IPAddress")
                if ip:
                    return f"http://{ip}:8001"
        finally:
            client.close()
    except Exception:
        pass
    return "http://localhost:8001"


# Configure fixture defaults before creating a backend runtime.
CM_URL = os.environ.get("CONTAINER_MANAGER_URL", "http://localhost:8001")
os.environ["COURSES_PATH"] = str(COURSES_DIR)
backend.src.runtime.CONTAINER_MANAGER_URL = CM_URL


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Isolated SQLite database with pre-seeded test students."""
    db_file = tmp_path / "app.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    init_db(db_file)

    with connect_db(db_file) as conn:
        create_student(
            conn,
            student_id="student-a-id",
            email="alice@ecole.fr",
            password_hash=hash_password("Password123!"),
        )
        create_student(
            conn,
            student_id="student-b-id",
            email="bob@ecole.fr",
            password_hash=hash_password("Password123!"),
        )
    return db_file


@pytest.fixture
def courses_path(monkeypatch):
    """Ensure COURSES_PATH points to the project courses."""
    path = get_courses_dir()
    monkeypatch.setenv("COURSES_PATH", str(path))
    return path


@pytest.fixture
def container_manager_url(monkeypatch):
    """Ensure CONTAINER_MANAGER_URL is set in environment and backend runtime."""
    url = detect_container_manager_url()
    monkeypatch.setenv("CONTAINER_MANAGER_URL", url)
    backend.src.runtime.CONTAINER_MANAGER_URL = url
    return url


@pytest.fixture
def client(tmp_db, courses_path):
    """Backend HTTP unit tests use an isolated database and a mocked manager."""
    with TestClient(app) as test_client:
        from backend.src.state import get_catalog, get_runtime_manager

        runtime_manager = get_runtime_manager()
        catalog = get_catalog()

        def respond(request):
            if request.url.path == "/v1/catalog":
                return httpx.Response(
                    200,
                    json={
                        "catalog_hash": catalog.catalog_hash,
                        "available": True,
                        "phase": "ready",
                        "build_report": {
                            ex.id: {"available": True}
                            for ex in catalog.exercises_by_id.values()
                        },
                    },
                )
            if request.url.path.endswith("/environment"):
                return httpx.Response(
                    200, json={"state": "stopped", "active_operation": None}
                )
            if request.url.path.endswith("/ssh-key"):
                return httpx.Response(200, json={"status": "ok"})
            return httpx.Response(
                404,
                json={
                    "error": {"code": "NOT_FOUND", "message": "Unknown mock endpoint"}
                },
            )

        runtime_manager.container_client.http_client.close()
        runtime_manager.container_client.http_client = httpx.Client(
            base_url="http://manager", transport=httpx.MockTransport(respond)
        )
        yield test_client


@pytest.fixture
def make_student_client(client):
    """Factory fixture creating isolated TestClient instances per student."""

    def _create(email, password="Password123!"):
        c = TestClient(app)
        res = c.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert res.status_code == 200
        data = res.json()
        csrf = data["csrf_token"]
        return {
            "client": c,
            "student": data["student"],
            "csrf_token": csrf,
            "headers": {"X-CSRF-Token": csrf},
        }

    return _create


@pytest.fixture
def auth_alice(make_student_client):
    """Helper returning an isolated authenticated session for Alice."""
    return make_student_client("alice@ecole.fr")


@pytest.fixture
def auth_bob(make_student_client):
    """Helper returning an isolated authenticated session for Bob."""
    return make_student_client("bob@ecole.fr")


@pytest.fixture
def valid_ed25519_key():
    """Generates a valid raw OpenSSH Ed25519 public key."""
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    )
    return pub.decode("ascii").strip()


@pytest.fixture
def clean_environments():
    """Ensures test containers and volumes are cleaned up before and after functional tests."""

    def _cleanup():
        try:
            import docker

            client = docker.from_env()
            for c in client.containers.list(all=True):
                for tid in TEST_STUDENT_IDS:
                    if tid in c.name:
                        try:
                            c.stop(timeout=2)
                        except Exception:
                            pass
                        try:
                            c.remove(force=True)
                        except Exception:
                            pass
            for v in client.volumes.list():
                for tid in TEST_STUDENT_IDS:
                    if tid in v.name:
                        try:
                            v.remove(force=True)
                        except Exception:
                            pass
        except Exception:
            pass

    _cleanup()
    yield
    _cleanup()
