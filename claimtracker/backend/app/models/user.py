"""
app/models/user.py
───────────────────
`users` table — authentication and role management.

`role` is no longer a column: since migration 0004 it is a FK to `roles`
exposed through a hybrid property, so `user.role` still reads as the plain
string ("user" / "reviewer" / "admin") that the JWT and API responses use.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.role import Role, RoleName


class UserRole(str):
    """Deprecated alias kept for import compatibility — use RoleName."""
    USER = RoleName.USER
    REVIEWER = RoleName.REVIEWER
    ADMIN = RoleName.ADMIN


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # ── Relationships ──────────────────────────────────────────────
    # lazy="joined": every read of `user.role` must not trigger IO, because
    # async SQLAlchemy raises MissingGreenlet on implicit lazy loads.
    role_obj: Mapped["Role"] = relationship(
        "Role", back_populates="users", lazy="joined"
    )
    claims: Mapped[list["Claim"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Claim", back_populates="user", cascade="all, delete-orphan"
    )
    reviews: Mapped[list["Review"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Review", back_populates="reviewer"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "AuditLog", back_populates="user"
    )
    exclusions_created: Mapped[list["Exclusion"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Exclusion", back_populates="created_by_user"
    )
    handbooks_uploaded: Mapped[list["HandbookVersion"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "HandbookVersion", back_populates="uploaded_by_user"
    )

    # ── Role as a string, backed by the lookup table ───────────────

    @hybrid_property
    def role(self) -> str:
        """The role name, e.g. "admin" — the value used in JWT claims."""
        return self.role_obj.name

    @role.inplace.expression
    @classmethod
    def _role_expression(cls):
        """SQL form, so `select(User).where(User.role == "admin")` still works."""
        return (
            select(Role.name)
            .where(Role.id == cls.role_id)
            .correlate(cls)
            .scalar_subquery()
        )

    def has_role(self, *names: str) -> bool:
        return self.role in names

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} role_id={self.role_id}>"
