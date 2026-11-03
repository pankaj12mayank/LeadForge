"""Pytest configuration: embedded PostgreSQL via pgserver for a real Postgres DB."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-prod-32chars")
os.environ.setdefault("RAZORPAY_WEBHOOK_SECRET", "whsec_test")

import pgserver  # noqa: E402

PGDATA = Path("C:/temp/pgdata_leadforge_tests")


@pytest.fixture(scope="session")
def pg_url():
    s = pgserver.get_server(str(PGDATA))
    url = s.get_uri().replace("postgres://", "postgresql+psycopg2://")
    os.environ["DATABASE_URL"] = url
    return url


@pytest.fixture(scope="session", autouse=True)
def schema(pg_url):
    from sqlalchemy import create_engine
    from app.db import Base

    eng = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True, future=True)
    Base.metadata.create_all(bind=eng)
    yield
    Base.metadata.drop_all(bind=eng)


@pytest.fixture()
def db():
    from sqlalchemy import create_engine
    from app.db import SessionLocal

    eng = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True, future=True)
    SessionLocal.configure(bind=eng)
    d = SessionLocal()
    yield d
    d.rollback()
    d.close()
