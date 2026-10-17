"""
app/models/audit_log.py
────────────────────────
`audit_logs` table — every AI decision and human action is logged here
with the full payload (prompt version, retrieved chunks, confidence).
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    claim_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("claims.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    # payload stores: prompt_version, model_name, retrieved_chunks, confidence, etc.
    payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    logged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    claim: Mapped[Optional["Claim"]] = relationship("Claim", back_populates="audit_logs")  # type: ignore[name-defined]  # noqa: F821
    user: Mapped[Optional["User"]] = relationship("User", back_populates="audit_logs")  # type: ignore[name-defined]  # noqa: F821

    def __repr__(self) -> str:
        return f"<AuditLog action={self.action} claim={self.claim_id}>"
