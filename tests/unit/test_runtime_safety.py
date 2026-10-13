"""Docker lifecycle and student-controlled filesystem regression tests."""

import json
import os
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from docker.errors import APIError, NotFound
from docker.models.containers import ContainerCollection
from fastapi.testclient import TestClient
from requests.exceptions import ReadTimeout

from container_manager.src.docker_runtime import (
    ConflictError,
    DockerRuntime,
    _read_evaluator_output,
)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    client = Mock()
    client.containers.list.return_value = []
    client.containers.get.side_effect = NotFound("Container does not exist")
    volume_path = tmp_path / "volume"
    volume_path.mkdir()
    client.volumes.get.return_value = SimpleNamespace(
        name="devops-instance-a-student-student-1", attrs={"Mountpoint": str(volume_path)}
    )
    # The manager runs as root; tests should also work as an ordinary user.
    monkeypatch.setattr(os, "fchown", lambda *args: None)
    return DockerRuntime(client, "instance-a", "localhost", snapshots_path=tmp_path / "snapshots")


def start(runtime, ssh_public_key="ssh-ed25519 test-key"):
    return runtime.start_dev_environment(
        student_id="student-1", operation_id="operation-1", exercise_id="exercise-1",
        exercise_name="Exercise", image_id="image-1", workspace_dir="exercise", ssh_public_key=ssh_public_key,
    )


def grade(runtime):
    return runtime.grade_student_exercise(
        student_id="student-1", operation_id="operation-1", exercise_id="exercise-1",
        evaluator_image_id="evaluator-1", workspace_dir="exercise", timeout_seconds=10,
    )


def evaluator(runtime):
    container = Mock()
    container.wait.return_value = {"StatusCode": 0}
    container.logs.return_value = b"evaluation log"

    def create(**kwargs):
        output_dir = next(path for path, mount in kwargs["volumes"].items() if mount["bind"] == "/result")
        (Path(output_dir) / "result.json").write_text(json.dumps({
            "schema_version": 1, "tests": [{"id": "test-1", "passed": True}],
        }))
        return container

    runtime.client.containers.create.side_effect = create
    return container


def test_student_cleanup_is_scoped_to_platform_instance(runtime):
    runtime.stop_student_environment("student-1", "operation-1")
    for call in runtime.client.containers.list.call_args_list:
        assert call.kwargs["filters"]["label"] == [
            "platform.app=devops-eval", "platform.instance=instance-a", "platform.student_id=student-1",
        ]


def test_platform_instances_use_separate_student_workspaces(runtime):
    volumes = {}

    def get_volume(name):
        if name not in volumes:
            raise NotFound("Volume does not exist")
        return volumes[name]

    def create_volume(name, labels):
        volumes[name] = SimpleNamespace(name=name, labels=labels)
        return volumes[name]

    runtime.client.volumes.get.side_effect = get_volume
    runtime.client.volumes.create.side_effect = create_volume
    other_runtime = DockerRuntime(runtime.client, "instance-b", "localhost")
    first = runtime.ensure_student_volume("student-1")
    second = other_runtime.ensure_student_volume("student-1")
    assert first.name != second.name
    assert first.labels["platform.instance"] == "instance-a"
    assert second.labels["platform.instance"] == "instance-b"
    assert runtime.ensure_student_volume("student-1") is first
    assert other_runtime.ensure_student_volume("student-1") is second


@pytest.mark.parametrize("method, args", [
    ("cleanup_on_startup", ()),
    ("allocate_port", ("student-1",)),
    ("find_all_student_containers", ("student-1",)),
])
def test_docker_listing_failure_is_not_treated_as_empty(runtime, method, args):
    runtime.client.containers.list.side_effect = APIError("Docker is unavailable")
    with pytest.raises(APIError, match="Docker is unavailable"):
        getattr(runtime, method)(*args)


@pytest.mark.parametrize("inspection_error", [NotFound("Evaluator was removed"), APIError("Docker is unavailable")])
def test_port_allocation_handles_only_disappearing_containers(runtime, inspection_error):
    # Exercise the SDK's separate list/inspect calls without a Docker daemon.
    runtime.client.containers = ContainerCollection(runtime.client)
    runtime.client.api.containers.return_value = [{"Id": "removed-evaluator"}, {"Id": "running-dev"}]
    runtime.client.api.inspect_container.side_effect = [inspection_error, {
        "Id": "running-dev",
        "NetworkSettings": {"Ports": {"22/tcp": [{"HostPort": "22000"}]}},
    }]
    if isinstance(inspection_error, NotFound):
        assert runtime.allocate_port("student-1") == 22001
        assert runtime._allocated_ports == {22001: "student-1"}
    else:
        with pytest.raises(APIError, match="Docker is unavailable"):
            runtime.allocate_port("student-1")
        assert runtime._allocated_ports == {}


def test_failed_start_removes_partial_container_and_releases_resources(runtime):
    container = runtime.client.containers.create.return_value
    container.start.side_effect = APIError("Port is already bound")
    with pytest.raises(APIError, match="Port is already bound"):
        start(runtime)
    container.remove.assert_called_once_with(force=True)
    assert runtime._allocated_ports == {}
    assert runtime.get_operation_info("student-1", "operation-1")["status"] == "failed"
    assert runtime.get_student_lock("student-1").acquire(blocking=False)
    runtime.get_student_lock("student-1").release()


def test_start_installs_current_ssh_key_before_starting_container(runtime):
    start(runtime, ssh_public_key="ssh-ed25519 test-key")
    key_path = runtime.get_student_volume_path("student-1") / ".ssh" / "authorized_keys"
    assert key_path.read_text() == "ssh-ed25519 test-key\n"
    assert key_path.stat().st_mode & 0o777 == 0o600


def test_start_requires_an_ssh_key_before_creating_resources(runtime):
    with pytest.raises(ValueError, match="SSH public key"):
        start(runtime, ssh_public_key=" ")
    runtime.client.containers.create.assert_not_called()
    runtime.client.volumes.get.assert_not_called()


def test_operation_identifier_cannot_replay_another_operation_type(runtime):
    original = start(runtime)
    with pytest.raises(ConflictError, match="identifiant"):
        grade(runtime)
    operation = runtime.get_operation_info("student-1", "operation-1")
    assert operation["status"] == "completed"
    assert operation["result"] == original


@pytest.mark.parametrize("failure", ["create", "wait", "remove"])
def test_evaluation_infrastructure_failure_clears_operation_and_lock(runtime, failure):
    container = evaluator(runtime)
    if failure == "create":
        runtime.client.containers.create.side_effect = APIError("Docker failed")
    else:
        getattr(container, failure).side_effect = APIError("Docker failed")
    with pytest.raises(APIError, match="Docker failed"):
        grade(runtime)
    assert runtime.get_operation_info("student-1", "operation-1")["status"] == "failed"
    assert runtime.get_student_lock("student-1").acquire(blocking=False)
    runtime.get_student_lock("student-1").release()
    if failure != "create":
        container.remove.assert_called_once_with(force=True)


def test_evaluation_wait_failure_is_not_reported_as_timeout(runtime):
    container = evaluator(runtime)
    container.wait.side_effect = APIError("Docker disconnected")
    with pytest.raises(APIError, match="Docker disconnected"):
        grade(runtime)
    assert runtime.get_operation_info("student-1", "operation-1")["status"] == "failed"


def test_evaluation_timeout_kills_and_removes_evaluator(runtime):
    container = evaluator(runtime)
    container.wait.side_effect = ReadTimeout("Evaluation exceeded deadline")
    result = grade(runtime)
    assert result.status == "error"
    assert result.error_code == "EVALUATION_TIMEOUT"
    container.kill.assert_called_once_with()
    container.remove.assert_called_once_with(force=True)
    assert runtime.get_operation_info("student-1", "operation-1")["status"] == "completed"


def test_evaluation_requires_successful_student_container_removal(runtime):
    student_container = Mock()
    student_container.remove.side_effect = APIError("Removal failed")
    runtime.client.containers.list.return_value = [student_container]
    with pytest.raises(APIError, match="Removal failed"):
        grade(runtime)
    runtime.client.containers.create.assert_not_called()
    assert runtime.get_operation_info("student-1", "operation-1")["status"] == "failed"


def test_valid_evaluation_is_completed_after_cleanup(runtime):
    container = evaluator(runtime)
    result = grade(runtime)
    assert result.status == "completed"
    assert [test.id for test in result.tests] == ["test-1"]
    container.remove.assert_called_once_with(force=True)
    create_kwargs = runtime.client.containers.create.call_args.kwargs
    output_dir = next(path for path, mount in create_kwargs["volumes"].items() if mount["bind"] == "/result")
    assert not Path(output_dir).exists()


def test_key_update_rejects_symlinked_ssh_directory(runtime, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "authorized_keys").write_text("original")
    (runtime.get_student_volume_path("student-1") / ".ssh").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        runtime.update_student_volume_key("student-1", "new key")
    assert (outside / "authorized_keys").read_text() == "original"


def test_key_update_replaces_symlink_without_modifying_its_target(runtime, tmp_path):
    outside = tmp_path / "outside-key"
    outside.write_text("original")
    ssh_dir = runtime.get_student_volume_path("student-1") / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "authorized_keys").symlink_to(outside)
    runtime.update_student_volume_key("student-1", "new key")
    assert outside.read_text() == "original"
    assert not (ssh_dir / "authorized_keys").is_symlink()
    assert (ssh_dir / "authorized_keys").read_text() == "new key\n"
    runtime.update_student_volume_key("student-1", "")
    assert (ssh_dir / "authorized_keys").read_text() == ""


@pytest.mark.parametrize("workspace, operation", [
    ("../outside", "operation-1"), ("/etc", "operation-1"),
    ("exercise", "../operation-1"), (".", "operation-1"),
])
def test_snapshot_rejects_path_traversal(runtime, workspace, operation):
    with pytest.raises(ValueError):
        runtime.create_exercise_snapshot("student-1", workspace, operation)


def test_snapshot_rejects_workspace_symlink_to_host_directory(runtime, tmp_path):
    (runtime.get_student_volume_path("student-1") / "exercise").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="outside"):
        runtime.create_exercise_snapshot("student-1", "exercise", "operation-1")


def test_snapshot_does_not_follow_student_file_symlinks(runtime, tmp_path):
    workspace = runtime.get_student_volume_path("student-1") / "exercise"
    workspace.mkdir()
    secret = tmp_path / "host-secret"
    secret.write_text("private")
    (workspace / "link").symlink_to(secret)
    snapshot_path = runtime.create_exercise_snapshot("student-1", "exercise", "operation-1")
    with tarfile.open(snapshot_path, "r:gz") as archive:
        assert archive.getmember("exercise/link").issym()
        assert all(member.size == 0 for member in archive)


def test_snapshot_directory_cannot_redirect_manager_writes(runtime, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    runtime.snapshots_path.mkdir()
    (runtime.snapshots_path / "student-1").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        runtime.create_exercise_snapshot("student-1", "exercise", "operation-1")
    assert list(outside.iterdir()) == []


def test_workspace_changes_do_not_modify_or_hide_manager_snapshots(runtime, tmp_path):
    volume = runtime.get_student_volume_path("student-1")
    workspace = volume / "exercise"
    workspace.mkdir()
    (workspace / "main.c").write_text("original source")
    snapshot_path = runtime.create_exercise_snapshot("student-1", "exercise", "operation-1")
    original = snapshot_path.read_bytes()
    assert snapshot_path == runtime.snapshots_path / "student-1" / "operation-1.tar.gz"
    (workspace / "main.c").write_text("changed source")
    workspace.rename(volume / "moved-exercise")
    workspace.symlink_to(tmp_path, target_is_directory=True)
    volume.chmod(0o777)
    # New archive reads do not require Docker or a student workspace lookup.
    runtime.client.volumes.get.side_effect = APIError("Docker is unavailable")
    with runtime.open_student_snapshot("student-1", "operation-1") as snapshot:
        assert snapshot.read() == original


def test_missing_snapshot_does_not_access_student_volume(runtime):
    runtime.client.volumes.get.side_effect = APIError("Docker is unavailable")
    assert runtime.open_student_snapshot("student-1", "operation-1") is None
    runtime.client.volumes.get.assert_not_called()


def test_snapshot_read_rejects_student_writable_archive_directory(runtime):
    snapshot_path = runtime.create_exercise_snapshot("student-1", "exercise", "operation-1")
    snapshot_path.parent.chmod(0o777)
    with pytest.raises(ValueError, match="private"):
        runtime.open_student_snapshot("student-1", "operation-1")


def test_snapshot_read_rejects_symlinks_and_survives_later_directory_swap(runtime, tmp_path):
    snapshot_path = runtime.create_exercise_snapshot("student-1", "exercise", "operation-1")
    original = snapshot_path.read_bytes()
    stream = runtime.open_student_snapshot("student-1", "operation-1")
    snapshots_dir = snapshot_path.parent
    snapshots_dir.rename(snapshots_dir.with_name("old-snapshots"))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "operation-1.tar.gz").write_bytes(b"host data")
    snapshots_dir.symlink_to(outside, target_is_directory=True)
    with stream:
        assert stream.read() == original
    with pytest.raises(OSError):
        runtime.open_student_snapshot("student-1", "operation-1")


@pytest.mark.parametrize("kind", ["symlink", "fifo", "large", "schema"])
def test_evaluator_result_rejects_unsafe_files(tmp_path, kind):
    path = tmp_path / "result.json"
    if kind == "symlink":
        outside = tmp_path / "outside"
        outside.write_text('{"tests": []}')
        path.symlink_to(outside)
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "large":
        path.write_text(" " * (1024 * 1024 + 1))
    else:
        path.write_text('{"schema_version": 99, "tests": []}')
    with pytest.raises((OSError, ValueError)):
        _read_evaluator_output(path)


def test_manager_api_validates_student_path_and_reports_docker_status_failure(runtime, monkeypatch):
    from container_manager.src.app import app
    from container_manager.src.api.v1 import environments

    monkeypatch.setattr(environments, "require_runtime", lambda: None)
    monkeypatch.setattr(environments, "get_docker_runtime", lambda: runtime)
    client = TestClient(app)
    invalid = client.get("/v1/students/bad.name/environment")
    assert invalid.status_code == 422
    runtime.client.containers.get.side_effect = APIError("Docker disconnected")
    unavailable = client.get("/v1/students/student-1/environment")
    assert unavailable.status_code == 502
    assert unavailable.json()["error"]["code"] == "ENVIRONMENT_STATUS_FAILED"


@pytest.mark.parametrize("key_fields", [{}, {"ssh_public_key": ""}, {"ssh_public_key": " \n\t "}])
def test_manager_start_api_requires_ssh_key(key_fields):
    from container_manager.src.app import app

    response = TestClient(app).post("/v1/students/student-1/start", json={
        "operation_id": "operation-1", "exercise_id": "exercise-1", **key_fields,
    })
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_snapshot_endpoint_streams_existing_archive_and_rejects_symlink(runtime, tmp_path, monkeypatch):
    from container_manager.src.app import app
    from container_manager.src.api.v1 import evaluations

    monkeypatch.setattr(evaluations, "require_runtime", lambda: None)
    monkeypatch.setattr(evaluations, "get_docker_runtime", lambda: runtime)
    snapshot = runtime.create_exercise_snapshot("student-1", "exercise", "operation-1")
    original = snapshot.read_bytes()
    client = TestClient(app)
    response = client.get("/v1/students/student-1/evaluations/operation-1/snapshot")
    assert response.status_code == 200
    assert response.content == original
    assert response.headers["content-type"] == "application/gzip"
    snapshot.unlink()
    outside = tmp_path / "outside"
    outside.write_text("private")
    snapshot.symlink_to(outside)
    rejected = client.get("/v1/students/student-1/evaluations/operation-1/snapshot")
    assert rejected.status_code == 404
    assert rejected.json()["error"]["code"] == "SNAPSHOT_NOT_FOUND"
