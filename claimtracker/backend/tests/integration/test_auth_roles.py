"""
tests/integration/test_auth_roles.py
─────────────────────────────────────
The `roles` lookup table (migration 0004) and the auth surface on top of it.

The point of these tests is that normalising `users.role` into a FK did **not**
change the API: registration still takes a role *name*, `user.role` still reads
as a string, the JWT still carries that string, and the guards still work off
the token alone.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ValidationError
from app.core.security import decode_access_token
from app.models.role import Role, RoleName
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services.auth_service import AuthService

pytestmark = pytest.mark.asyncio


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@example.com"


# ── The lookup table itself ───────────────────────────────────────────────────

async def test_three_roles_are_seeded(db_session: AsyncSession, roles):
    rows = (await db_session.execute(select(Role))).scalars().all()
    assert {r.name for r in rows} == {"user", "reviewer", "admin"}
    assert all(r.description for r in rows), "each role should document itself"


async def test_role_names_are_unique(db_session: AsyncSession, roles):
    from sqlalchemy.exc import IntegrityError

    db_session.add(Role(id=uuid.uuid4(), name="admin", description="duplicate"))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


# ── Registration resolves the name to a FK ────────────────────────────────────

@pytest.mark.parametrize("role_name", [RoleName.USER, RoleName.REVIEWER, RoleName.ADMIN])
async def test_register_assigns_the_right_role(
    db_session: AsyncSession, roles, role_name: str
):
    email = _email()
    user = await AuthService(db_session).register(
        RegisterRequest(
            email=email, password="SecurePass1", full_name="Test Person", role=role_name
        )
    )

    assert user.role_id == roles[role_name].id
    # The hybrid property reads back the plain name — the API contract.
    assert user.role == role_name


async def test_register_defaults_to_the_user_role(db_session: AsyncSession, roles):
    user = await AuthService(db_session).register(
        RegisterRequest(email=_email(), password="SecurePass1", full_name="Default Role")
    )
    assert user.role == RoleName.USER


async def test_register_with_an_unseeded_role_is_rejected(
    db_session: AsyncSession, roles
):
    """
    Guards against a half-migrated database: the FK cannot be resolved, so the
    service must say so rather than writing a NULL role_id.
    """
    svc = AuthService(db_session)
    request = RegisterRequest(
        email=_email(), password="SecurePass1", full_name="Ghost", role=RoleName.ADMIN
    )

    # Simulate the roles table not having been seeded.
    await db_session.execute(
        Role.__table__.delete().where(Role.name == RoleName.ADMIN)
    )

    with pytest.raises(ValidationError, match="does not exist"):
        await svc.register(request)

    await db_session.rollback()


async def test_duplicate_email_still_conflicts(db_session: AsyncSession, roles):
    svc = AuthService(db_session)
    email = _email()
    await svc.register(
        RegisterRequest(email=email, password="SecurePass1", full_name="First")
    )

    with pytest.raises(ConflictError, match="already registered"):
        await svc.register(
            RegisterRequest(email=email, password="SecurePass1", full_name="Second")
        )


# ── The hybrid property, in Python and in SQL ─────────────────────────────────

async def test_user_role_is_queryable_in_sql(db_session: AsyncSession, roles):
    """
    `User.role` has a SQL expression form, so it can still be used in a WHERE
    clause even though it is no longer a column.
    """
    svc = AuthService(db_session)
    admin_email = _email()
    await svc.register(
        RegisterRequest(
            email=admin_email,
            password="SecurePass1",
            full_name="An Admin",
            role=RoleName.ADMIN,
        )
    )
    await svc.register(
        RegisterRequest(email=_email(), password="SecurePass1", full_name="A User")
    )

    admins = (
        await db_session.execute(select(User).where(User.role == RoleName.ADMIN))
    ).unique().scalars().all()

    assert admin_email in {u.email for u in admins}
    assert all(u.role == RoleName.ADMIN for u in admins)


async def test_has_role_helper(db_session: AsyncSession, roles):
    user = await AuthService(db_session).register(
        RegisterRequest(
            email=_email(),
            password="SecurePass1",
            full_name="Reviewer Person",
            role=RoleName.REVIEWER,
        )
    )

    assert user.has_role(RoleName.REVIEWER, RoleName.ADMIN) is True
    assert user.has_role(RoleName.ADMIN) is False


async def test_loading_a_user_does_not_need_a_second_query(
    db_session: AsyncSession, roles
):
    """
    `role_obj` is lazy="joined", so reading `.role` on a freshly loaded user
    must not trigger IO — an implicit lazy load would raise MissingGreenlet
    under async SQLAlchemy.
    """
    email = _email()
    await AuthService(db_session).register(
        RegisterRequest(
            email=email,
            password="SecurePass1",
            full_name="Joined Load",
            role=RoleName.REVIEWER,
        )
    )
    db_session.expire_all()

    loaded = (
        await db_session.execute(select(User).where(User.email == email))
    ).unique().scalar_one()

    # No await, no exception: the role came back in the same SELECT.
    assert loaded.role == RoleName.REVIEWER


# ── JWT still carries the role name ───────────────────────────────────────────

async def test_login_token_carries_the_role_name(db_session: AsyncSession, roles):
    svc = AuthService(db_session)
    email = _email()
    await svc.register(
        RegisterRequest(
            email=email,
            password="SecurePass1",
            full_name="Token Person",
            role=RoleName.REVIEWER,
        )
    )

    token_response = await svc.login(
        LoginRequest(email=email, password="SecurePass1")
    )

    assert token_response.role == RoleName.REVIEWER
    payload = decode_access_token(token_response.access_token)
    assert payload["role"] == RoleName.REVIEWER
    assert payload["sub"] == str(token_response.user_id)


# ── End to end over HTTP ──────────────────────────────────────────────────────

async def test_register_login_me_round_trip(client: AsyncClient, roles):
    email = _email()

    r = await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "SecurePass1",
            "full_name": "Round Trip",
            "role": "reviewer",
        },
    )
    assert r.status_code == 201
    assert r.json()["role"] == "reviewer"

    r = await client.post(
        "/auth/login", json={"email": email, "password": "SecurePass1"}
    )
    assert r.status_code == 200
    token = r.json()["access_token"]
    assert r.json()["role"] == "reviewer"

    r = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == email
    assert body["role"] == "reviewer"


async def test_unknown_role_is_rejected_by_the_schema(client: AsyncClient, roles):
    """The API surface is still a closed set of names, validated by Pydantic."""
    r = await client.post(
        "/auth/register",
        json={
            "email": _email(),
            "password": "SecurePass1",
            "full_name": "Bad Role",
            "role": "superuser",
        },
    )
    assert r.status_code == 422


# ── Role guards ───────────────────────────────────────────────────────────────

async def _token_for(client: AsyncClient, role: str) -> str:
    email = _email()
    await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "SecurePass1",
            "full_name": f"{role} person",
            "role": role,
        },
    )
    r = await client.post(
        "/auth/login", json={"email": email, "password": "SecurePass1"}
    )
    return r.json()["access_token"]


@pytest.mark.parametrize(
    "role,expected",
    [("user", 403), ("reviewer", 403), ("admin", 200)],
)
async def test_admin_only_endpoint_enforces_the_role(
    client: AsyncClient, roles, role: str, expected: int
):
    """`GET /exclusions` is admin-only; the guard reads the JWT claim."""
    token = await _token_for(client, role)
    r = await client.get("/exclusions", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == expected


async def test_missing_token_is_unauthorised(client: AsyncClient, roles):
    r = await client.get("/exclusions")
    assert r.status_code == 403  # HTTPBearer rejects a missing Authorization header


async def test_garbage_token_is_unauthorised(client: AsyncClient, roles):
    r = await client.get(
        "/exclusions", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert r.status_code == 401
