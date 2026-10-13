"""System health, readiness, and catalog endpoints for Container Manager."""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from shared.contracts import ManagerCatalogResponse

from ...core.exceptions import http_error
from ...services.state import (
    get_build_manager,
    get_docker_runtime,
    get_instance_id,
    get_startup_error,
)
from ...services.state import (
    get_catalog as state_get_catalog,
)

router = APIRouter(tags=["system"])


@router.get("/health")
def get_health():
    """Only completed startup makes this service healthy."""
    bm = get_build_manager()
    err = get_startup_error()
    phase = bm.phase if bm else ("failed" if err else "preparing")
    ready = bool(bm and bm.is_ready and phase == "ready" and not err)
    if ready:
        runtime = get_docker_runtime()
        try:
            if runtime is None:
                raise RuntimeError("Docker runtime not initialized")
            runtime.client.ping()
        except Exception as error:
            ready = False
            err = str(error)
    return JSONResponse(status_code=200 if ready else 503, content={
        "status": "ok" if ready else "error" if err else "preparing",
        "instance_id": get_instance_id(),
        "phase": phase,
        "error": err,
    })


@router.get("/catalog", response_model=ManagerCatalogResponse)
def get_catalog():
    """Reports image build status and catalog hash match for the backend."""
    cat = state_get_catalog()
    bm = get_build_manager()
    if not cat or not bm:
        raise http_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "MANAGER_UNAVAILABLE",
            "Catalog or manager not initialized",
        )
    return {
        "catalog_hash": cat.catalog_hash,
        "available": get_health().status_code == 200,
        "phase": bm.phase,
        "build_report": bm.report,
    }
