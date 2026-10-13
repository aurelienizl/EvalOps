"""Functional test fixtures for EvalOps: instances, Minion personas, and cleanups."""

import os
from dataclasses import dataclass
from typing import Dict

import docker
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi.testclient import TestClient

from tests.conftest import detect_container_manager_url, get_courses_dir

COURSES_DIR = get_courses_dir()
MINION_NAMES = ["kevin", "bob", "stuart", "dave", "otto", "mel"]
MINION_IDS = {name: f"{name}-id" for name in MINION_NAMES}


@dataclass
class Minion:
    id: str
    name: str
    email: str
    client: TestClient
    csrf_token: str
    headers: Dict[str, str]
    ssh_public_key: str


def _clean_minion_docker_resources():
    """Removes any container or volume belonging to test minions."""
    try:
        client = docker.from_env()
        for c in client.containers.list(all=True):
            for mid in MINION_IDS.values():
                if mid in c.name:
                    try:
                        c.stop(timeout=2)
                    except Exception:
                        pass
                    try:
                        c.remove(force=True)
                    except Exception:
                        pass
        for v in client.volumes.list():
            for mid in MINION_IDS.values():
                if mid in v.name:
                    try:
                        v.remove(force=True)
                    except Exception:
                        pass
    except Exception:
        pass


@pytest.fixture(scope="package")
def functional_instance(tmp_path_factory):
    """Initializes a fresh backend instance and container manager connection."""
    _clean_minion_docker_resources()

    db_dir = tmp_path_factory.mktemp("functional_db")
    db_file = db_dir / "app.db"
    cm_url = detect_container_manager_url()

    os.environ["DATABASE_PATH"] = str(db_file)
    os.environ["COURSES_PATH"] = str(COURSES_DIR)
    os.environ["CONTAINER_MANAGER_URL"] = cm_url

    import backend.src.runtime

    backend.src.runtime.CONTAINER_MANAGER_URL = cm_url

    import backend.src.app as backend_app
    from backend.src.core.security import hash_password
    from backend.src.db import connect_db, create_student, init_db
    from backend.src.runtime import RuntimeManager
    from backend.src.state import set_catalog, set_runtime_manager
    from shared.catalog import parse_and_validate_catalog

    init_db(db_file)
    catalog = parse_and_validate_catalog(COURSES_DIR)
    runtime_manager = RuntimeManager(catalog)
    set_catalog(catalog)
    set_runtime_manager(runtime_manager)

    # Seed all minions in database
    with connect_db(db_file) as conn:
        for name in MINION_NAMES:
            create_student(
                conn,
                student_id=MINION_IDS[name],
                email=f"{name}@ecole.fr",
                password_hash=hash_password("Banana123!"),
            )

    yield {
        "app": backend_app.app,
        "db_file": db_file,
        "cm_url": cm_url,
    }

    _clean_minion_docker_resources()
    runtime_manager.close()
    set_catalog(None)
    set_runtime_manager(None)


@pytest.fixture(autouse=True)
def clean_functional_state(request):
    """Ensures each functional test runs with isolated progress, quotas, and Docker containers."""
    if request.node.get_closest_marker("capacity"):
        yield
        return
    functional_instance = request.getfixturevalue("functional_instance")
    yield
    db_file = functional_instance["db_file"]
    from backend.src.db import connect_db

    with connect_db(db_file) as conn:
        conn.execute("DELETE FROM student_exercises")
        conn.execute("DELETE FROM evaluations")
        conn.execute("DELETE FROM student_runtime")
    _clean_minion_docker_resources()


@pytest.fixture(scope="package")
def students(functional_instance) -> Dict[str, Minion]:
    """Provides authenticated Minions: Kevin, Bob, Stuart, Dave, Otto, Mel."""
    app = functional_instance["app"]
    minions = {}

    for name in MINION_NAMES:
        client = TestClient(app)
        # 1. Login
        login_res = client.post(
            "/api/v1/auth/login",
            json={"email": f"{name}@ecole.fr", "password": "Banana123!"},
        )
        assert login_res.status_code == 200, f"Failed to login {name}"
        csrf_token = login_res.json()["csrf_token"]
        headers = {"X-CSRF-Token": csrf_token}

        # 2. Generate and set valid Ed25519 key
        priv = ed25519.Ed25519PrivateKey.generate()
        pub_bytes = priv.public_key().public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )
        key_str = pub_bytes.decode("ascii").strip()

        key_res = client.put(
            "/api/v1/profile/ssh-key", headers=headers, json={"public_key": key_str}
        )
        assert key_res.status_code == 200, (
            f"Failed to set SSH key for {name}: {key_res.text}"
        )

        minions[name] = Minion(
            id=MINION_IDS[name],
            name=name,
            email=f"{name}@ecole.fr",
            client=client,
            csrf_token=csrf_token,
            headers=headers,
            ssh_public_key=key_str,
        )

    return minions


# Direct individual minion fixtures for maximum developer convenience:
@pytest.fixture
def kevin(students) -> Minion:
    return students["kevin"]


@pytest.fixture
def bob(students) -> Minion:
    return students["bob"]


@pytest.fixture
def stuart(students) -> Minion:
    return students["stuart"]


@pytest.fixture
def dave(students) -> Minion:
    return students["dave"]


@pytest.fixture
def otto(students) -> Minion:
    return students["otto"]


@pytest.fixture
def mel(students) -> Minion:
    return students["mel"]


@pytest.fixture
def simulation_instance(request, tmp_path):
    """A fresh Compose project with real HTTP services and isolated student resources."""
    from tests.functional.simulation_support import create_simulation_instance

    with create_simulation_instance(
        tmp_path,
        student_count=request.config.getoption("--simulation-students"),
    ) as instance:
        yield instance
