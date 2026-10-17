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

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_ENV == "development",
    pool_pre_ping=True,
    # SQLite doesn't support pool settings; they're ignored for sqlite+aiosqlite
    pool_size=10 if "postgresql" in settings.DATABASE_URL else 1,
    max_overflow=20 if "postgresql" in settings.DATABASE_URL else 0,
)

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
