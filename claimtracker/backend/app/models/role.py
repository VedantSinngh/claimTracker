"""
app/models/role.py
───────────────────
`roles` lookup table.

Replaces the former `users.role` enum column (see migration 0004).
A lookup table rather than an enum because:

- Adding a role is an INSERT, not an ALTER TYPE (Postgres enums cannot drop
  a value at all, and adding one cannot run inside a transaction block).
- Role metadata (description, and later permissions) has somewhere to live.
- It is third normal form: `description` depends on the role, not on the user.

The three seeded names — "user", "reviewer", "admin" — are contractual: they
appear in JWT claims and in the `require_role` guards, so the API surface is
unchanged by this refactor.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class RoleName(str):
    """Canonical role names — keep in sync with the 0004 seed data."""
    USER = "user"
    REVIEWER = "reviewer"
    ADMIN = "admin"

    @classmethod
    def all(cls) -> list[str]:
        return [cls.USER, cls.REVIEWER, cls.ADMIN]


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    users: Mapped[list["User"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "User", back_populates="role_obj"
    )

    def __repr__(self) -> str:
        return f"<Role id={self.id} name={self.name}>"
