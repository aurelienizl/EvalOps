"""Health state is local; no database schema flags are needed."""

from dataclasses import dataclass
from contextlib import nullcontext
import asyncio
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn


@dataclass
class HealthState:
    ready: bool = False


def create_health_app(state):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/ready")
    async def ready():
        return JSONResponse(
            dict(status="ready" if state.ready else "not_ready"),
            status_code=200 if state.ready else 503,
        )

    @app.get("/healthz")
    async def alive():
        return dict(status="alive")

    return app


async def serve_health(settings, state, stop):
    server = uvicorn.Server(
        uvicorn.Config(
            create_health_app(state),
            host=settings.health_host,
            port=settings.health_port,
            log_level="warning",
        )
    )
    server.capture_signals = nullcontext
    task = asyncio.create_task(server.serve())
    try:
        while not stop.is_set():
            if task.done():
                await task
                raise RuntimeError("Health server stopped")
            await asyncio.sleep(0.2)
    finally:
        server.should_exit = True
        await task
