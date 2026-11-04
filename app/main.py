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

# Design theme tokens (exact values from docs/design/LeadForge Design System.html)
_env.globals["THEME_LIGHT"] = '--bg:#F3F4F6;--surf:#FFFFFF;--surf2:#EBEEF2;--line:#D9DEE5;--fg:#0E1116;--mut:#4B5563;--acc:#C8431A;--accfg:#FFFFFF;--acc2:#0B7A75;--ok:#157347;--ring:rgba(200,67,26,.22);--shadow:0 1px 2px rgba(16,24,40,.06),0 10px 28px -10px rgba(16,24,40,.10);--shadow-h:0 18px 40px -14px rgba(16,24,40,.28);'
_env.globals["THEME_DARK"] = '--bg:#0B0D10;--surf:#14181D;--surf2:#1C2128;--line:#2A313A;--fg:#EEF1F5;--mut:#9AA4B2;--acc:#FF7A45;--accfg:#1A0B04;--acc2:#3DC9C2;--ok:#4ADE80;--ring:rgba(255,122,69,.28);--shadow:0 1px 2px rgba(0,0,0,.4),0 10px 28px -10px rgba(0,0,0,.5);--shadow-h:0 18px 44px -14px rgba(0,0,0,.7);'


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
