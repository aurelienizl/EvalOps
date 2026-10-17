"""FastAPI application and feature routers."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from .core.config import load_settings, Settings
from .database.connection import open_pool, close_pool
from .api import auth, profile, catalog, environments, evaluations, admin, health


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await open_pool(app.state.settings)
    try:
        yield
    finally:
        await close_pool(app.state.pool)


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="EvalOps API", version="2.0.0", lifespan=lifespan)
    app.state.settings = settings or load_settings()
    for module in (auth, profile, catalog, environments, evaluations, admin):
        app.include_router(module.router, prefix="/api/v1")
    app.include_router(health.router)
    return app


if __name__ == "__main__":
    import uvicorn

    config = load_settings()
    uvicorn.run(create_app(config), host=config.host, port=config.port)
