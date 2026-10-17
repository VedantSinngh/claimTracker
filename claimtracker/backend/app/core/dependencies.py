"""
app/core/dependencies.py
─────────────────────────
FastAPI dependency functions.
All injected via Depends() — no global state in routers.
"""
from typing import AsyncGenerator
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.security import decode_access_token
from app.models.role import RoleName

_bearer = HTTPBearer()


# ─── Database session ──────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async SQLAlchemy session; always closes on exit."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


# ─── Current user ──────────────────────────────────────────────────────────────

class CurrentUser:
    """Parsed JWT payload attached to request state."""

    def __init__(self, user_id: UUID, role: str, email: str = ""):
        self.user_id = user_id
        self.role = role
        self.email = email


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> CurrentUser:
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = UUID(payload["sub"])
        role = payload["role"]
    except (JWTError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return CurrentUser(user_id=user_id, role=role)


# ─── Role guards ───────────────────────────────────────────────────────────────

def require_role(*allowed_roles: str):
    """
    Factory: returns a dependency that checks the caller's role.

    The role is read from the JWT `role` claim, which carries the *name* from
    the `roles` lookup table (see migration 0004) — so guards stay a cheap
    string comparison with no extra query, and normalising the column did not
    change the token format. Pass `RoleName` constants rather than literals.
    """

    async def _guard(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' is not permitted for this action.",
            )
        return current_user

    return _guard


require_reviewer = require_role(RoleName.REVIEWER, RoleName.ADMIN)
require_admin = require_role(RoleName.ADMIN)
