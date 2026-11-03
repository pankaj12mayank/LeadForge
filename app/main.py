from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db import Base, engine
from app.models import *  # noqa: F401

templates = Jinja2Templates(directory="app/templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=settings.LOG_LEVEL.upper())
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

    @app.get("/healthz", response_class=PlainTextResponse)
    async def healthz():
        return "ok"

    from app.auth.router import router as auth_router
    from app.routers import landing, dashboard, searches, leads, billing, admin, api

    app.include_router(auth_router)
    app.include_router(landing.router)
    app.include_router(dashboard.router)
    app.include_router(searches.router)
    app.include_router(leads.router)
    app.include_router(billing.router)
    app.include_router(admin.router)
    app.include_router(api.router)

    @app.exception_handler(Exception)
    async def global_exc(request: Request, exc: Exception):
        logging.exception("unhandled error: %s", exc)
        return HTMLResponse("Internal Server Error", status_code=500)

    return app


app = create_app()
