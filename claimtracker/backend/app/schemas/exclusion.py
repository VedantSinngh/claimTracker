"""
app/schemas/exclusion.py
─────────────────────────
"""
import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ExclusionCreateRequest(BaseModel):
    term: str = Field(min_length=2, max_length=255)
    description: Optional[str] = None


class ExclusionResponse(BaseModel):
    id: uuid.UUID
    term: str
    description: Optional[str]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ExclusionListResponse(BaseModel):
    items: List[ExclusionResponse]
    total: int
