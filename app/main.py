from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db import Base, engine
from app.models import *  # noqa: F401

templates = Jinja2Templates(directory="app/templates")

# Register component macros globally so all templates can use them
from jinja2 import FileSystemLoader
_env = templates.env
_macros = _env.get_template("components/macros.html")
_env.globals["button"] = _macros.module.button
_env.globals["input"] = _macros.module.input
_env.globals["select"] = _macros.module.select
_env.globals["badge"] = _macros.module.badge
_env.globals["stat_card"] = _macros.module.stat_card
_env.globals["table"] = _macros.module.table
_env.globals["pagination"] = _macros.module.pagination
_env.globals["progress"] = _macros.module.progress
_env.globals["bar_chart"] = _macros.module.bar_chart
_env.globals["line_chart"] = _macros.module.line_chart
_env.globals["donut_chart"] = _macros.module.donut_chart


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=settings.LOG_LEVEL.upper())
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

    @app.get("/healthz", response_class=PlainTextResponse)
    async def healthz():
        return "ok"

    app.mount("/static", StaticFiles(directory="app/static"), name="static")

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
