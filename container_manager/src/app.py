"""Container-manager startup and API assembly."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import docker
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from shared.catalog import parse_and_validate_catalog

from .api.v1 import api_v1_router
from .builds import BuildManager
from .core.config import (
    APT_CACHE_URL,
    COURSES_PATH,
    PLATFORM_INSTANCE,
    SSH_BIND_ADDRESS,
    SSH_HOST,
    SSH_PORT_MAX,
    SSH_PORT_MIN,
)
from .docker_runtime import DockerRuntime
from .services import state

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("container_manager")


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.set_catalog(None)
    state.set_build_manager(None)
    state.set_docker_runtime(None)
    state.set_startup_error(None)
    client = None
    try:
        if not 1 <= SSH_PORT_MIN <= SSH_PORT_MAX <= 65535:
            raise ValueError("SSH port range must satisfy 1 <= SSH_PORT_MIN <= SSH_PORT_MAX <= 65535")
        catalog = parse_and_validate_catalog(COURSES_PATH)
        client = docker.from_env()
        client.ping()
        runtime = DockerRuntime(
            docker_client=client,
            platform_instance=PLATFORM_INSTANCE,
            ssh_host=SSH_HOST,
            ssh_bind_address=SSH_BIND_ADDRESS,
            ssh_port_min=SSH_PORT_MIN,
            ssh_port_max=SSH_PORT_MAX,
        )
        builder = BuildManager(client, state.get_instance_id(), APT_CACHE_URL)
        state.set_catalog(catalog)
        state.set_docker_runtime(runtime)
        state.set_build_manager(builder)
        runtime.cleanup_on_startup()
        # Complete builds before Uvicorn starts accepting requests.
        builder.run_all_builds(catalog)
        logger.info("Container manager ready after startup builds")
    except Exception as error:
        state.set_startup_error(str(error))
        builder = state.get_build_manager()
        if builder:
            builder.phase = "failed"
            builder.is_ready = False
        if client:
            client.close()
        logger.exception("Container manager startup failed")
        raise
    try:
        yield
    finally:
        builder.is_ready = False
        client.close()
        state.set_catalog(None)
        state.set_build_manager(None)
        state.set_docker_runtime(None)


app = FastAPI(title="EvalOps Container Manager", version="1.0.0", lifespan=lifespan)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, error: HTTPException):
    content = error.detail if isinstance(error.detail, dict) and "error" in error.detail else {
        "error": {"code": "HTTP_ERROR", "message": str(error.detail)},
    }
    return JSONResponse(status_code=error.status_code, content=content, headers=error.headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, error: RequestValidationError):
    return JSONResponse(status_code=422, content={
        "error": {"code": "INVALID_REQUEST", "message": "Requête invalide"},
    })


app.include_router(api_v1_router)
