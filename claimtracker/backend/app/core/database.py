"""
app/core/database.py
─────────────────────
SQLAlchemy 2.0 async engine + session factory.
Works with both PostgreSQL (asyncpg) and SQLite (aiosqlite)
through the same DATABASE_URL env variable.
"""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()


def _engine_kwargs(database_url: str) -> dict:
    """
    Pool options differ by backend.

    `pool_size` / `max_overflow` belong to QueuePool, which only Postgres uses
    here. SQLite does not merely ignore them — SQLAlchemy picks StaticPool (or
    NullPool) for aiosqlite and then raises
    `TypeError: Invalid argument(s) 'pool_size','max_overflow'`, so they must
    not be passed at all on the SQLite dev path.
    """
    kwargs: dict = {
        "echo": settings.APP_ENV == "development",
        "pool_pre_ping": True,
    }
    if database_url.startswith("postgresql"):
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20
    return kwargs


engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs(settings.DATABASE_URL))

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    """Shared declarative base — import this in every model."""
    pass
