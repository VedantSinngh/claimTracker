"""
app/models/claim.py
────────────────────
`claims`, `claim_documents`, and `extracted_fields` tables.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    DATE,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.types import JSONColumn


class ClaimStatus(str):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (
        Index("ix_claims_status", "status"),
        Index("ix_claims_created_at", "created_at"),
        Index("ix_claims_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    patient_name: Mapped[str] = mapped_column(String(255), nullable=False)
    claim_item: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    date_of_treatment: Mapped[date] = mapped_column(DATE, nullable=False)
    medical_facility: Mapped[str] = mapped_column(String(255), nullable=False)
    claim_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(
            "PENDING",
            "PROCESSING",
            "ACCEPTED",
            "REJECTED",
            "NEEDS_REVIEW",
            name="claim_status_enum",
        ),
        nullable=False,
        default="PENDING",
        server_default="PENDING",
    )
    confidence_score: Mapped[Optional[float]] = mapped_column(nullable=True)
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
    user: Mapped["User"] = relationship("User", back_populates="claims")  # type: ignore[name-defined]  # noqa: F821
    documents: Mapped[list["ClaimDocument"]] = relationship(
        "ClaimDocument", back_populates="claim", cascade="all, delete-orphan"
    )
    extracted_fields: Mapped[Optional["ExtractedFields"]] = relationship(
        "ExtractedFields", back_populates="claim", uselist=False, cascade="all, delete-orphan"
    )
    decisions: Mapped[list["Decision"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Decision", back_populates="claim", cascade="all, delete-orphan"
    )
    reviews: Mapped[list["Review"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Review", back_populates="claim", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "AuditLog", back_populates="claim"
    )

    def __repr__(self) -> str:
        return f"<Claim id={self.id} status={self.status} amount={self.claim_amount}>"


class ClaimDocument(Base):
    __tablename__ = "claim_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    raw_ocr_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    claim: Mapped["Claim"] = relationship("Claim", back_populates="documents")

    def __repr__(self) -> str:
        return f"<ClaimDocument id={self.id} file={self.file_name}>"


class ExtractedFields(Base):
    __tablename__ = "extracted_fields"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    patient_name_extracted: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    diagnosis: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    facility_extracted: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    date_extracted: Mapped[Optional[date]] = mapped_column(DATE, nullable=True)
    itemised_charges: Mapped[Optional[dict]] = mapped_column(JSONColumn, nullable=True)
    total_amount_extracted: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    llm_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    claim: Mapped["Claim"] = relationship("Claim", back_populates="extracted_fields")

    def __repr__(self) -> str:
        return f"<ExtractedFields claim_id={self.claim_id} diagnosis={self.diagnosis}>"
