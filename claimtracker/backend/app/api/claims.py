"""
app/api/claims.py
──────────────────
Claims router — submit, list, and retrieve claims.
Background task runs the full AI pipeline after a claim is accepted.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, CurrentUser
from app.core.exceptions import NotFoundError
from app.models.role import RoleName
from app.schemas.claim import ClaimListResponse, ClaimResponse
from app.services.claim_service import ClaimService

router = APIRouter(prefix="/claims", tags=["claims"])


@router.post("", response_model=ClaimResponse, status_code=status.HTTP_201_CREATED)
async def submit_claim(
    background_tasks: BackgroundTasks,
    # Form fields
    patient_name: str = Form(..., min_length=2, max_length=255),
    claim_item: str = Form(...),
    reason: str = Form(...),
    address: str = Form(...),
    date_of_treatment: str = Form(..., description="YYYY-MM-DD"),
    medical_facility: str = Form(...),
    claim_amount: float = Form(..., gt=0),
    description: Optional[str] = Form(None),
    # File upload
    bill_file: UploadFile = File(..., description="PDF, JPG, or PNG bill"),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Submit a new insurance claim with a bill file.
    The AI pipeline runs as a background task; poll GET /claims/{id} for status.
    """
    svc = ClaimService(db)
    claim, pipeline_fn = await svc.submit_claim(
        user_id=current_user.user_id,
        patient_name=patient_name,
        claim_item=claim_item,
        reason=reason,
        address=address,
        date_of_treatment=date_of_treatment,
        medical_facility=medical_facility,
        claim_amount=claim_amount,
        description=description,
        bill_file=bill_file,
    )
    background_tasks.add_task(pipeline_fn)
    return claim


@router.get("", response_model=ClaimListResponse)
async def list_claims(
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List claims. Regular users see only their own; reviewers/admins see all."""
    svc = ClaimService(db)
    user_id = (
        None
        if current_user.role in (RoleName.REVIEWER, RoleName.ADMIN)
        else current_user.user_id
    )
    return await svc.list_claims(
        user_id=user_id, status=status, page=page, page_size=page_size
    )


@router.get("/{claim_id}", response_model=ClaimResponse)
async def get_claim(
    claim_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get full claim detail including extracted fields, decisions, and citations."""
    svc = ClaimService(db)
    claim = await svc.get_claim(claim_id=claim_id, requesting_user=current_user)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim
