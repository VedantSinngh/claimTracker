"""
app/models/review.py
─────────────────────
`reviews` table — human-in-the-loop override log.
Every reviewer action (approve / reject / override) is stored
with the before and after status for a full audit trail.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=False
    )
    outcome: Mapped[str] = mapped_column(
        Enum("APPROVED", "REJECTED", "OVERRIDE", name="review_outcome_enum"),
        nullable=False,
    )
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    previous_status: Mapped[str] = mapped_column(
        Enum(
            "PENDING", "PROCESSING", "ACCEPTED", "REJECTED", "NEEDS_REVIEW",
            name="review_prev_status_enum",
        ),
        nullable=False,
    )
    new_status: Mapped[str] = mapped_column(
        Enum(
            "PENDING", "PROCESSING", "ACCEPTED", "REJECTED", "NEEDS_REVIEW",
            name="review_new_status_enum",
        ),
        nullable=False,
    )
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    claim: Mapped["Claim"] = relationship("Claim", back_populates="reviews")  # type: ignore[name-defined]  # noqa: F821
    reviewer: Mapped["User"] = relationship("User", back_populates="reviews")  # type: ignore[name-defined]  # noqa: F821

    def __repr__(self) -> str:
        return f"<Review id={self.id} outcome={self.outcome} claim={self.claim_id}>"
