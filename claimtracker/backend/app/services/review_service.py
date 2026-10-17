"""
app/services/review_service.py
───────────────────────────────
Human-in-the-loop reviewer override logic.
"""
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.audit_log import AuditLog
from app.models.review import Review
from app.repositories.claim_repo import ClaimRepository
from app.repositories.review_repo import ReviewRepository
from app.schemas.review import ReviewCreateRequest

logger = get_logger(__name__)

# Map review outcome → new claim status
_OUTCOME_STATUS_MAP = {
    "APPROVED": "ACCEPTED",
    "REJECTED": "REJECTED",
    "OVERRIDE": None,  # new_status comes from the request body
}


class ReviewService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._claim_repo = ClaimRepository(session)
        self._review_repo = ReviewRepository(session)

    async def submit_review(
        self,
        *,
        claim_id: UUID,
        reviewer_id: UUID,
        request: ReviewCreateRequest,
    ) -> Optional[Review]:
        claim = await self._claim_repo.get_by_id(claim_id)
        if claim is None:
            return None

        if claim.status not in ("NEEDS_REVIEW", "ACCEPTED", "REJECTED"):
            raise ValidationError(
                f"Claim status '{claim.status}' cannot be reviewed. "
                "Only NEEDS_REVIEW, ACCEPTED, or REJECTED claims can be overridden."
            )

        # Determine new status
        if request.outcome == "OVERRIDE":
            if not request.new_status:
                raise ValidationError("new_status is required for OVERRIDE outcome.")
            new_status = request.new_status
        else:
            new_status = _OUTCOME_STATUS_MAP[request.outcome]

        previous_status = claim.status

        # Update claim status
        await self._claim_repo.update_status(claim_id, new_status)

        # Create review record
        review = Review(
            claim_id=claim_id,
            reviewer_id=reviewer_id,
            outcome=request.outcome,
            comment=request.comment,
            previous_status=previous_status,
            new_status=new_status,
        )
        review = await self._review_repo.create(review)

        # Audit log
        audit = AuditLog(
            claim_id=claim_id,
            user_id=reviewer_id,
            action="HUMAN_OVERRIDE",
            payload={
                "outcome": request.outcome,
                "previous_status": previous_status,
                "new_status": new_status,
                "comment": request.comment,
            },
        )
        self._session.add(audit)
        await self._session.commit()

        logger.info(
            "review_submitted",
            claim_id=str(claim_id),
            reviewer_id=str(reviewer_id),
            outcome=request.outcome,
            previous_status=previous_status,
            new_status=new_status,
        )
        return review
