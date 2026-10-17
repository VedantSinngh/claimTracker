"""
tests/integration/test_claim_flow.py
─────────────────────────────────────
Integration tests for the auth + claim submission flow.
Uses the in-memory SQLite DB and ASGI test client from conftest.py.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_register_and_login(client: AsyncClient):
    # Register
    register_payload = {
        "email": "testuser@example.com",
        "password": "SecurePass1",
        "full_name": "Test User",
        "role": "user",
    }
    r = await client.post("/auth/register", json=register_payload)
    assert r.status_code == 201
    data = r.json()
    assert data["email"] == "testuser@example.com"
    assert data["role"] == "user"

    # Login
    r = await client.post(
        "/auth/login",
        json={"email": "testuser@example.com", "password": "SecurePass1"},
    )
    assert r.status_code == 200
    token_data = r.json()
    assert "access_token" in token_data
    assert token_data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    payload = {
        "email": "dup@example.com",
        "password": "SecurePass1",
        "full_name": "Dup User",
    }
    await client.post("/auth/register", json=payload)
    r = await client.post("/auth/register", json=payload)
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    await client.post(
        "/auth/register",
        json={"email": "wrong@example.com", "password": "SecurePass1", "full_name": "Wrong"},
    )
    r = await client.post(
        "/auth/login",
        json={"email": "wrong@example.com", "password": "badpassword"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_claims_require_auth(client: AsyncClient):
    r = await client.get("/claims")
    assert r.status_code == 403  # No bearer token


@pytest.mark.asyncio
async def test_me_endpoint(client: AsyncClient):
    # Register and login
    await client.post(
        "/auth/register",
        json={"email": "me@example.com", "password": "SecurePass1", "full_name": "Me User"},
    )
    login_r = await client.post(
        "/auth/login",
        json={"email": "me@example.com", "password": "SecurePass1"},
    )
    token = login_r.json()["access_token"]

    r = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == "me@example.com"
