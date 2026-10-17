"""
app/api/reviews.py
───────────────────
Reviewer queue and override endpoint.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_reviewer, CurrentUser
from app.schemas.review import ReviewCreateRequest, ReviewResponse
from app.services.review_service import ReviewService

router = APIRouter(prefix="/claims", tags=["reviews"])


@router.post("/{claim_id}/review", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
async def post_review(
    claim_id: uuid.UUID,
    body: ReviewCreateRequest,
    current_user: CurrentUser = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    """Reviewer approves, rejects, or overrides a claim decision."""
    svc = ReviewService(db)
    review = await svc.submit_review(
        claim_id=claim_id,
        reviewer_id=current_user.user_id,
        request=body,
    )
    if review is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    return review
