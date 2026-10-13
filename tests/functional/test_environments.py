"""Functional tests for environment lifecycle, port allocation, and quotas using Kevin & Bob."""

import docker
from docker.errors import NotFound
from container_manager.src.docker_runtime import (
    CONTAINER_CPU_LIMIT,
    CONTAINER_MEM_LIMIT,
    CONTAINER_PIDS_LIMIT,
)


def test_environment_start_quotas_and_stop(kevin):
    """Kevin launches an environment, checks quotas on Docker, and stops it cleanly."""
    docker_client = docker.from_env()

    # 1. Start hello-c environment
    res = kevin.client.post("/api/v1/exercises/hello-c/start", headers=kevin.headers)
    assert res.status_code == 200
    data = res.json()
    assert data["state"] == "running"
    assert data["exercise"]["id"] == "hello-c"

    ssh_port = data["ssh"]["port"]
    assert 22000 <= ssh_port <= 22999
    assert data["ssh"]["user"] == "student"

    # 2. Verify Docker container quotas directly
    container_name = f"devops-evalops-prod-dev-{kevin.id}"
    container = docker_client.containers.get(container_name)
    assert container.status == "running"

    host_config = container.attrs["HostConfig"]
    assert host_config["NanoCpus"] == CONTAINER_CPU_LIMIT
    assert host_config["Memory"] == 512 * 1024 * 1024
    assert host_config["PidsLimit"] == CONTAINER_PIDS_LIMIT

    # 3. GET /environment confirms state
    env_res = kevin.client.get("/api/v1/environment")
    assert env_res.status_code == 200
    assert env_res.json()["state"] == "running"

    # 4. Stop environment
    stop_res = kevin.client.post("/api/v1/environment/stop", headers=kevin.headers)
    assert stop_res.status_code == 200
    assert stop_res.json()["state"] == "stopped"

    # 5. Verify container removed from Docker
    try:
        docker_client.containers.get(container_name)
        assert False, "Container should have been deleted"
    except NotFound:
        pass


def test_parallel_environments_independent_ports(kevin, bob):
    """Kevin and Bob can run parallel environments on distinct SSH ports without conflict."""
    # Start Kevin
    res_k = kevin.client.post("/api/v1/exercises/hello-c/start", headers=kevin.headers)
    assert res_k.status_code == 200
    port_k = res_k.json()["ssh"]["port"]

    # Start Bob
    res_b = bob.client.post("/api/v1/exercises/fibo-c/start", headers=bob.headers)
    assert res_b.status_code == 200
    port_b = res_b.json()["ssh"]["port"]

    # Ports must be distinct
    assert port_k != port_b

    # Clean up both
    kevin.client.post("/api/v1/environment/stop", headers=kevin.headers)
    bob.client.post("/api/v1/environment/stop", headers=bob.headers)
