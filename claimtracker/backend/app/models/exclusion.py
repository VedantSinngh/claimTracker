"""
app/models/exclusion.py
────────────────────────
`exclusions` table — admin-editable list of excluded diagnoses.
Unique index on `term` for fast lookup and deduplication.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Exclusion(Base):
    __tablename__ = "exclusions"
    __table_args__ = (Index("ix_exclusions_term", "term", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    term: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    created_by_user: Mapped[Optional["User"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "User", back_populates="exclusions_created"
    )

    def __repr__(self) -> str:
        return f"<Exclusion term={self.term} active={self.is_active}>"
