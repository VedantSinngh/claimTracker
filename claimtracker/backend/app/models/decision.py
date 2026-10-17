"""
app/models/decision.py
───────────────────────
`decisions` table — one row per pipeline run.
Stores full AI reasoning, confidence, cited clauses, prompt version,
and retrieved RAG chunks for complete auditability.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.types import JSONColumn


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    outcome: Mapped[str] = mapped_column(
        Enum("ACCEPTED", "REJECTED", "NEEDS_REVIEW", name="decision_outcome_enum"),
        nullable=False,
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cited_clauses: Mapped[Optional[list]] = mapped_column(JSONColumn, nullable=True)
    executive_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    retrieved_chunks: Mapped[Optional[list]] = mapped_column(JSONColumn, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    claim: Mapped["Claim"] = relationship("Claim", back_populates="decisions")  # type: ignore[name-defined]  # noqa: F821

    def __repr__(self) -> str:
        return f"<Decision id={self.id} outcome={self.outcome} confidence={self.confidence_score}>"
