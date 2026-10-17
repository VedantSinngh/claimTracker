"""Add reviews table with previous_status and new_status columns.

Revision ID: 0002
Revises: 0001
Create Date: 2024-01-02 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enums for review outcome and status transitions
    review_outcome = postgresql.ENUM("APPROVED", "REJECTED", "OVERRIDE", name="review_outcome_enum")
    review_prev_status = postgresql.ENUM(
        "PENDING", "PROCESSING", "ACCEPTED", "REJECTED", "NEEDS_REVIEW",
        name="review_prev_status_enum",
    )
    review_new_status = postgresql.ENUM(
        "PENDING", "PROCESSING", "ACCEPTED", "REJECTED", "NEEDS_REVIEW",
        name="review_new_status_enum",
    )

    review_outcome.create(op.get_bind(), checkfirst=True)
    review_prev_status.create(op.get_bind(), checkfirst=True)
    review_new_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("claims.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reviewer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=False),
        sa.Column("outcome", sa.Enum("APPROVED", "REJECTED", "OVERRIDE", name="review_outcome_enum"), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "previous_status",
            sa.Enum("PENDING", "PROCESSING", "ACCEPTED", "REJECTED", "NEEDS_REVIEW", name="review_prev_status_enum"),
            nullable=False,
        ),
        sa.Column(
            "new_status",
            sa.Enum("PENDING", "PROCESSING", "ACCEPTED", "REJECTED", "NEEDS_REVIEW", name="review_new_status_enum"),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_reviews_claim_id", "reviews", ["claim_id"])
    op.create_index("ix_reviews_reviewer_id", "reviews", ["reviewer_id"])


def downgrade() -> None:
    op.drop_index("ix_reviews_reviewer_id", table_name="reviews")
    op.drop_index("ix_reviews_claim_id", table_name="reviews")
    op.drop_table("reviews")
    postgresql.ENUM(name="review_new_status_enum").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="review_prev_status_enum").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="review_outcome_enum").drop(op.get_bind(), checkfirst=True)
