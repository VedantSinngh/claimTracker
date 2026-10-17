"""
app/models/handbook.py
───────────────────────
`handbook_versions` table.
Only one version is active at a time (is_active flag).
The FAISS index path is stored so it can be loaded on startup.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class HandbookVersion(Base):
    __tablename__ = "handbook_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    version_tag: Mapped[str] = mapped_column(String(100), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    chunk_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    faiss_index_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    uploaded_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    uploaded_by_user: Mapped[Optional["User"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "User", back_populates="handbooks_uploaded"
    )

    def __repr__(self) -> str:
        return f"<HandbookVersion tag={self.version_tag} active={self.is_active}>"
