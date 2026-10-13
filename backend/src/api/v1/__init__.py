"""API v1 router aggregating all endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from .admin import router as admin_router
from .auth import router as auth_router
from .courses import router as courses_router
from .environment import router as environment_router
from .evaluations import router as evaluations_router
from .profile import router as profile_router
from .system import router as system_router

api_v1_router = APIRouter(prefix="/api/v1")

# Mount sub-routers
api_v1_router.include_router(auth_router)
api_v1_router.include_router(profile_router)
api_v1_router.include_router(courses_router)
api_v1_router.include_router(evaluations_router)
api_v1_router.include_router(environment_router)
api_v1_router.include_router(admin_router)
api_v1_router.include_router(system_router)

__all__ = ["api_v1_router"]
