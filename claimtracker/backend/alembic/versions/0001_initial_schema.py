"""Initial schema — all 9 tables with indexes, FKs, and enums.

Revision ID: 0001
Revises: 
Create Date: 2024-01-01 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.types import JSONColumn

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Enums ─────────────────────────────────────────────────────
    user_role = postgresql.ENUM("user", "reviewer", "admin", name="user_role_enum")
    claim_status = postgresql.ENUM(
        "PENDING", "PROCESSING", "ACCEPTED", "REJECTED", "NEEDS_REVIEW",
        name="claim_status_enum",
    )
    decision_outcome = postgresql.ENUM(
        "ACCEPTED", "REJECTED", "NEEDS_REVIEW", name="decision_outcome_enum"
    )

    user_role.create(op.get_bind(), checkfirst=True)
    claim_status.create(op.get_bind(), checkfirst=True)
    decision_outcome.create(op.get_bind(), checkfirst=True)

    # ── users ──────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", sa.Enum("user", "reviewer", "admin", name="user_role_enum"), nullable=False, server_default="user"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ── claims ─────────────────────────────────────────────────────
    op.create_table(
        "claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("patient_name", sa.String(255), nullable=False),
        sa.Column("claim_item", sa.String(255), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("date_of_treatment", sa.Date(), nullable=False),
        sa.Column("medical_facility", sa.String(255), nullable=False),
        sa.Column("claim_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Enum("PENDING", "PROCESSING", "ACCEPTED", "REJECTED", "NEEDS_REVIEW", name="claim_status_enum"), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_claims_status", "claims", ["status"])
    op.create_index("ix_claims_created_at", "claims", ["created_at"])
    op.create_index("ix_claims_user_id", "claims", ["user_id"])

    # ── claim_documents ────────────────────────────────────────────
    op.create_table(
        "claim_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("claims.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("raw_ocr_text", sa.Text(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ── extracted_fields ───────────────────────────────────────────
    op.create_table(
        "extracted_fields",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("claims.id", ondelete="CASCADE"), nullable=False),
        sa.Column("patient_name_extracted", sa.String(255), nullable=True),
        sa.Column("diagnosis", sa.String(255), nullable=True),
        sa.Column("facility_extracted", sa.String(255), nullable=True),
        sa.Column("date_extracted", sa.Date(), nullable=True),
        sa.Column("itemised_charges", JSONColumn, nullable=True),
        sa.Column("total_amount_extracted", sa.Numeric(12, 2), nullable=True),
        sa.Column("llm_model", sa.String(100), nullable=True),
        sa.Column("prompt_version", sa.String(50), nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("claim_id", name="uq_extracted_fields_claim_id"),
    )

    # ── decisions ──────────────────────────────────────────────────
    op.create_table(
        "decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("claims.id", ondelete="CASCADE"), nullable=False),
        sa.Column("outcome", sa.Enum("ACCEPTED", "REJECTED", "NEEDS_REVIEW", name="decision_outcome_enum"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("cited_clauses", JSONColumn, nullable=True),
        sa.Column("executive_summary", sa.Text(), nullable=True),
        sa.Column("model_name", sa.String(100), nullable=True),
        sa.Column("prompt_version", sa.String(50), nullable=True),
        sa.Column("retrieved_chunks", JSONColumn, nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ── exclusions ─────────────────────────────────────────────────
    op.create_table(
        "exclusions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("term", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("term", name="uq_exclusions_term"),
    )
    op.create_index("ix_exclusions_term", "exclusions", ["term"], unique=True)

    # ── handbook_versions ──────────────────────────────────────────
    op.create_table(
        "handbook_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("version_tag", sa.String(100), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("faiss_index_path", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ── audit_logs ─────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("claims.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("payload", JSONColumn, nullable=True),
        sa.Column("ip_address", sa.String(50), nullable=True),
        sa.Column("logged_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("handbook_versions")
    op.drop_table("exclusions")
    op.drop_table("decisions")
    op.drop_table("extracted_fields")
    op.drop_table("claim_documents")
    op.drop_table("claims")
    op.drop_table("users")

    # Drop enums
    postgresql.ENUM(name="decision_outcome_enum").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="claim_status_enum").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="user_role_enum").drop(op.get_bind(), checkfirst=True)
