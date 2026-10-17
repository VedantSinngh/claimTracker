"""
app/schemas/handbook.py
────────────────────────
"""
import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class HandbookResponse(BaseModel):
    id: uuid.UUID
    version_tag: str
    chunk_count: Optional[int]
    is_active: bool
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class HandbookListResponse(BaseModel):
    items: List[HandbookResponse]
    total: int
