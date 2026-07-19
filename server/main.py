from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from server.api import router as api_router
from server.auth import validate_admin_auth_settings
from server.config import settings
from server.db import get_database_status, init_database, run_database_migrations
from server.debug import router as debug_router
from server.health import build_readiness_status
from server.webhooks.github import router as github_webhook_router

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)


def _public_database_status() -> dict[str, object]:
    database = get_database_status()
    database.pop("url", None)
    return database


def _system_status_payload(*, status: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": settings.app_name,
        "status": status,
    }
    if settings.detailed_public_health:
        payload["environment"] = settings.app_env
        payload["database"] = _public_database_status()
    return payload


def _public_readiness_payload(readiness: dict[str, object]) -> dict[str, object]:
    if settings.detailed_public_health:
        return readiness
    return {"status": readiness["status"]}


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_database()
    run_database_migrations()
    yield

def create_app() -> FastAPI:
    validate_admin_auth_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0-beta.2",
        description="GitHub triage assistant for open source maintainers.",
        lifespan=lifespan,
        docs_url="/docs" if settings.expose_api_docs else None,
        redoc_url="/redoc" if settings.expose_api_docs else None,
        openapi_url="/openapi.json" if settings.expose_api_docs else None,
    )

    trusted_hosts = [host.strip() for host in settings.trusted_hosts.split(",") if host.strip()]
    if trusted_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)

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
        return _system_status_payload(status="running")

    @app.get("/healthz", tags=["system"])
    def healthz() -> dict[str, object]:
        return _system_status_payload(status="ok")

    @app.get("/readyz", tags=["system"])
    def readyz() -> JSONResponse:
        readiness = build_readiness_status()
        status_code = 200 if readiness["status"] == "ok" else 503
        return JSONResponse(status_code=status_code, content=_public_readiness_payload(readiness))

    return app


app = create_app()
