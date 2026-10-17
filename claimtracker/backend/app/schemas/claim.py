"""
app/schemas/claim.py
─────────────────────
Pydantic v2 schemas for claim endpoints.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class ClaimCreateRequest(BaseModel):
    patient_name: str = Field(min_length=2, max_length=255)
    claim_item: str = Field(min_length=2, max_length=255)
    reason: str = Field(min_length=2, max_length=255)
    address: str = Field(min_length=5)
    date_of_treatment: date
    medical_facility: str = Field(min_length=2, max_length=255)
    claim_amount: Decimal = Field(gt=0)
    description: Optional[str] = None

    @field_validator("claim_amount")
    @classmethod
    def amount_precision(cls, v: Decimal) -> Decimal:
        return round(v, 2)


class ExtractedFieldsResponse(BaseModel):
    patient_name_extracted: Optional[str]
    diagnosis: Optional[str]
    facility_extracted: Optional[str]
    date_extracted: Optional[date]
    itemised_charges: Optional[Dict[str, Any]]
    total_amount_extracted: Optional[Decimal]
    llm_model: Optional[str]
    prompt_version: Optional[str]
    extracted_at: datetime

    model_config = {"from_attributes": True}


class DecisionResponse(BaseModel):
    id: uuid.UUID
    outcome: str
    reason: Optional[str]
    cited_clauses: Optional[List[Any]]
    executive_summary: Optional[str]
    confidence_score: Optional[float]
    model_name: Optional[str]
    prompt_version: Optional[str]
    decided_at: datetime

    model_config = {"from_attributes": True}


class ClaimDocumentResponse(BaseModel):
    id: uuid.UUID
    file_name: str
    mime_type: str
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class ClaimResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    patient_name: str
    claim_item: str
    reason: str
    address: str
    date_of_treatment: date
    medical_facility: str
    claim_amount: Decimal
    description: Optional[str]
    status: str
    confidence_score: Optional[float]
    created_at: datetime
    updated_at: datetime
    documents: List[ClaimDocumentResponse] = []
    extracted_fields: Optional[ExtractedFieldsResponse] = None
    decisions: List[DecisionResponse] = []

    model_config = {"from_attributes": True}


class ClaimListResponse(BaseModel):
    items: List[ClaimResponse]
    total: int
    page: int
    page_size: int
