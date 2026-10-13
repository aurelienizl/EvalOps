"""System health and readiness endpoints for EvalOps Backend."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ...state import get_catalog, get_runtime_manager

router = APIRouter(tags=["system"])


@router.get("/health")
def get_health():
    return {"status": "ok"}


@router.get("/ready")
def get_ready():
    catalog = get_catalog()
    runtime_manager = get_runtime_manager()

    if not catalog or not runtime_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "PLATFORM_PREPARING", "message": "Backend initialisation in progress"}},
        )

    mgr_cat = runtime_manager.get_manager_catalog()
    if not mgr_cat or not mgr_cat.get("available"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "MANAGER_UNAVAILABLE", "message": "Container manager not ready or builds in progress"}},
        )

    if mgr_cat.get("catalog_hash") != catalog.catalog_hash:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "CATALOG_MISMATCH", "message": "Catalog fingerprint differs between services"}},
        )

    return {"status": "ready"}
