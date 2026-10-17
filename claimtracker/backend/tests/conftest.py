"""
tests/conftest.py
──────────────────
Shared pytest fixtures.

Two database backends are available:

- **SQLite in-memory** (default, used by almost every test) — fast, no Docker.
- **PostgreSQL via testcontainers** (`pg_session`) — only for tests that need
  real Postgres SQL: `DATE_TRUNC`, `FILTER (WHERE …)`, `RANK() OVER`, CTEs.
  See `tests/integration/test_analytics_postgres.py`. These tests skip
  automatically when Docker is unavailable.

Because the schema here is built with `Base.metadata.create_all` rather than
Alembic, the `roles` rows that migration 0004 seeds must be inserted by hand —
`_seed_roles` does that, and every user fixture depends on it.
"""
import asyncio
from typing import AsyncGenerator, Optional

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.dependencies import get_db
from app.main import app
from app.models.role import Role, RoleName

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

# Mirrors the seed in migration 0004 so tests and production agree.
ROLE_DESCRIPTIONS = {
    RoleName.USER: "Submits claims and views only their own.",
    RoleName.REVIEWER: "Works the NEEDS_REVIEW queue; can approve, reject or override a decision.",
    RoleName.ADMIN: "Full access: handbook ingestion, exclusions management, all claims.",
}


async def seed_roles(session: AsyncSession) -> dict[str, Role]:
    """Insert the three canonical roles if absent; return them by name."""
    from app.repositories.role_repo import RoleRepository

    repo = RoleRepository(session)
    roles = {}
    for name in RoleName.all():
        roles[name] = await repo.get_or_create(name, ROLE_DESCRIPTIONS[name])
    await session.commit()
    return roles


@pytest_asyncio.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_db():
    """Create all tables once per test session, then seed the roles lookup."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with TestSessionLocal() as session:
        await seed_roles(session)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def reset_database(session: AsyncSession) -> None:
    """
    Delete every row, then re-seed the roles lookup.

    A rollback is not enough for isolation here: the services under test call
    `commit()` themselves (ClaimService, HandbookService, ReviewService all
    do), so their writes outlive the fixture's rollback and leak into later
    tests — an ingested handbook left `is_active=True` would make the "no
    active handbook" RAG tests pass vacuously, and committed claims would skew
    the pagination counts.

    Tables are deleted child-first (`sorted_tables` reversed) to respect the
    foreign keys.
    """
    for table in reversed(Base.metadata.sorted_tables):
        await session.execute(table.delete())
    await session.commit()
    await seed_roles(session)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a session over a freshly emptied, role-seeded database."""
    async with TestSessionLocal() as session:
        await reset_database(session)
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def roles(db_session: AsyncSession) -> dict[str, Role]:
    """The three seeded roles, keyed by name (db_session already seeded them)."""
    from app.repositories.role_repo import RoleRepository

    repo = RoleRepository(db_session)
    return {name: await repo.get_by_name(name) for name in RoleName.all()}


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP test client with the DB dependency overridden."""
    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


# ── PostgreSQL fixtures (analytics tests only) ────────────────────────────────

def _postgres_container():
    """
    Start a throwaway Postgres 16 container, or return None with a reason
    when that is not possible (no testcontainers installed, no Docker daemon).
    """
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        return None, "testcontainers is not installed (pip install -r requirements-dev.txt)"

    try:
        container = PostgresContainer("postgres:16-alpine")
        container.start()
        return container, None
    except Exception as exc:  # Docker not running, image pull failed, …
        return None, f"could not start a Postgres container: {exc}"


@pytest.fixture(scope="session")
def postgres_url() -> Optional[str]:
    """
    An asyncpg URL for a live Postgres, or None when Docker is unavailable.

    In CI a service container is used instead: when POSTGRES_TEST_URL is set we
    honour it and never touch Docker directly.
    """
    import os

    env_url = os.getenv("POSTGRES_TEST_URL")
    if env_url:
        yield env_url
        return

    container, reason = _postgres_container()
    if container is None:
        pytest.skip(reason)

    try:
        # testcontainers hands back a psycopg2 URL; swap the driver.
        url = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql+asyncpg://"
        )
        yield url
    finally:
        container.stop()


@pytest_asyncio.fixture(scope="session")
async def pg_engine(postgres_url: str):
    """Async engine against the live Postgres, with the full schema created."""
    # NullPool: a session-scoped engine must not hold connections that were
    # opened on a different event loop.
    engine = create_async_engine(postgres_url, echo=False, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_session(pg_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    A Postgres session whose work is rolled back afterwards.

    Analytics tests aggregate over whole tables, so each test must start from a
    clean slate: every table is truncated before the test runs.
    """
    maker = async_sessionmaker(
        bind=pg_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    async with maker() as session:
        from sqlalchemy import text

        await session.execute(
            text(
                "TRUNCATE audit_logs, reviews, decisions, extracted_fields, "
                "claim_documents, claims, exclusions, handbook_versions, "
                "users, roles RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()
        await seed_roles(session)
        yield session
        await session.rollback()
