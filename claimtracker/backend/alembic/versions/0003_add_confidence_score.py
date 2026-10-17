"""Add confidence_score to claims and decisions tables.

Revision ID: 0003
Revises: 0002
Create Date: 2024-01-03 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add confidence_score to claims (denormalized for fast filtering in queues)
    op.add_column(
        "claims",
        sa.Column("confidence_score", sa.Float(), nullable=True),
    )
    # Add confidence_score to decisions (source of truth for the AI confidence)
    op.add_column(
        "decisions",
        sa.Column("confidence_score", sa.Float(), nullable=True),
    )
    # Index on confidence_score for reviewer queue filtering (low-confidence claims)
    op.create_index("ix_claims_confidence_score", "claims", ["confidence_score"])


def downgrade() -> None:
    op.drop_index("ix_claims_confidence_score", table_name="claims")
    op.drop_column("decisions", "confidence_score")
    op.drop_column("claims", "confidence_score")
