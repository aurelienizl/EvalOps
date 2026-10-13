"""Aggregation of Container Manager v1 API routers."""

from __future__ import annotations

from fastapi import APIRouter

from .environments import router as environments_router
from .evaluations import router as evaluations_router
from .operations import router as operations_router
from .system import router as system_router

api_v1_router = APIRouter(prefix="/v1")

api_v1_router.include_router(system_router)
api_v1_router.include_router(environments_router)
api_v1_router.include_router(evaluations_router)
api_v1_router.include_router(operations_router)

__all__ = ["api_v1_router"]
