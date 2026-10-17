"""
app/schemas/review.py
──────────────────────
"""
import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class ReviewCreateRequest(BaseModel):
    outcome: Literal["APPROVED", "REJECTED", "OVERRIDE"]
    comment: Optional[str] = None
    # Override target status (required for OVERRIDE outcome)
    new_status: Optional[Literal["ACCEPTED", "REJECTED", "NEEDS_REVIEW"]] = None


class ReviewResponse(BaseModel):
    id: uuid.UUID
    claim_id: uuid.UUID
    reviewer_id: uuid.UUID
    outcome: str
    comment: Optional[str]
    previous_status: str
    new_status: str
    reviewed_at: datetime

    model_config = {"from_attributes": True}
