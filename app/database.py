"""Database engine and session management.

Uses SQLite by default so the tool runs locally with zero setup. For a durable
deployment (e.g. Railway), set a Postgres URL via ``ROBOCALL_DB_URL`` or the
standard ``DATABASE_URL`` that Railway's Postgres plugin provides.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


def _resolve_db_url() -> str:
    """Pick the database URL and normalize provider-specific quirks.

    Precedence: ROBOCALL_DB_URL, then DATABASE_URL (Railway/Heroku style),
    then a local SQLite file. The legacy ``postgres://`` scheme that some
    providers still hand out is rewritten to ``postgresql://`` because
    SQLAlchemy 2.x no longer accepts the old form.
    """
    url = (
        os.environ.get("ROBOCALL_DB_URL")
        or os.environ.get("DATABASE_URL")
        or "sqlite:///./robocall_log.db"
    )
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    return url


DB_URL = _resolve_db_url()

# check_same_thread is only needed for SQLite + a multithreaded web server.
_connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}

# pool_pre_ping avoids stale-connection errors on managed Postgres that closes
# idle connections; it is harmless for SQLite.
engine = create_engine(
    DB_URL, connect_args=_connect_args, pool_pre_ping=True, future=True
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency that yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables if they do not yet exist."""
    # Import models so they are registered on the metadata before create_all.
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
