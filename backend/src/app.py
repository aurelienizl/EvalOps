"""FastAPI application for Backend service."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from shared.catalog import parse_and_validate_catalog

from .api.v1 import api_v1_router
from .db import init_db
from .runtime import RuntimeManager
from .state import set_catalog, set_runtime_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("backend")

@asynccontextmanager
async def lifespan(app: FastAPI):
    set_catalog(None)
    set_runtime_manager(None)
    init_db()
    catalog = parse_and_validate_catalog(os.environ.get("COURSES_PATH", "/courses"))
    runtime_manager = RuntimeManager(catalog)
    set_catalog(catalog)
    set_runtime_manager(runtime_manager)
    logger.info(f"Backend started with catalog hash {catalog.catalog_hash}")
    try:
        yield
    finally:
        runtime_manager.close()
        set_catalog(None)
        set_runtime_manager(None)


app = FastAPI(title="EvalOps Backend", version="1.0.0", lifespan=lifespan)


# --- Custom Exception Handlers for Unified Error Format ---

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    headers = getattr(exc, "headers", None)
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail, headers=headers)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": "HTTP_ERROR", "message": str(exc.detail)}},
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": {"code": "INVALID_REQUEST", "message": "Requête invalide"}},
    )


# --- Include Modular API Routers ---
app.include_router(api_v1_router)
