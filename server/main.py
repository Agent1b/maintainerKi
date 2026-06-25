from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from server.api import router as api_router
from server.config import settings
from server.db import ensure_schema_upgrades, get_database_status, get_engine, init_database
from server.debug import router as debug_router
from server.health import build_readiness_status
from server.models import Base
from server.webhooks.github import router as github_webhook_router

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)


def _public_database_status() -> dict[str, object]:
    database = get_database_status()
    database.pop("url", None)
    return database


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_database()
    Base.metadata.create_all(bind=get_engine())
    ensure_schema_upgrades()
    yield

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="GitHub triage assistant for open source maintainers.",
    lifespan=lifespan,
)

allowed_origins = [
    origin.strip()
    for origin in settings.dashboard_allowed_origins.split(",")
    if origin.strip()
]
if allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(github_webhook_router)
app.include_router(debug_router)
app.include_router(api_router)


@app.get("/", tags=["system"])
def root() -> dict[str, object]:
    return {
        "name": settings.app_name,
        "status": "running",
        "environment": settings.app_env,
        "database": _public_database_status(),
    }


@app.get("/healthz", tags=["system"])
def healthz() -> dict[str, object]:
    return {
        "status": "ok",
        "environment": settings.app_env,
        "database": _public_database_status(),
    }


@app.get("/readyz", tags=["system"])
def readyz() -> JSONResponse:
    readiness = build_readiness_status()
    status_code = 200 if readiness["status"] == "ok" else 503
    return JSONResponse(status_code=status_code, content=readiness)
