"""
app/repositories/claim_repo.py
───────────────────────────────
ClaimRepository — paginated list, status filter, user filter, eager loading.
"""
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.claim import Claim, ClaimDocument, ExtractedFields
from app.repositories.base import BaseRepository


class ClaimRepository(BaseRepository[Claim]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Claim, session)

    async def get_with_details(self, claim_id: UUID) -> Optional[Claim]:
        """Load claim with all relationships for the detail endpoint."""
        result = await self._session.execute(
            select(Claim)
            .where(Claim.id == claim_id)
            .options(
                selectinload(Claim.documents),
                selectinload(Claim.extracted_fields),
                selectinload(Claim.decisions),
                selectinload(Claim.reviews),
            )
        )
        return result.scalar_one_or_none()

    async def list_claims(
        self,
        *,
        user_id: Optional[UUID] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> Tuple[List[Claim], int]:
        """Return (claims, total_count) with optional filters."""
        query = select(Claim).options(
            selectinload(Claim.documents),
            selectinload(Claim.decisions),
        )
        count_query = select(func.count()).select_from(Claim)

        if user_id is not None:
            query = query.where(Claim.user_id == user_id)
            count_query = count_query.where(Claim.user_id == user_id)
        if status is not None:
            query = query.where(Claim.status == status)
            count_query = count_query.where(Claim.status == status)

        query = query.order_by(Claim.created_at.desc()).offset(skip).limit(limit)

        results = await self._session.execute(query)
        count_result = await self._session.execute(count_query)
        return list(results.scalars().all()), count_result.scalar_one()

    async def update_status(self, claim_id: UUID, status: str, confidence: Optional[float] = None) -> Optional[Claim]:
        claim = await self.get_by_id(claim_id)
        if claim is None:
            return None
        claim.status = status  # type: ignore[assignment]
        if confidence is not None:
            claim.confidence_score = confidence  # type: ignore[assignment]
        await self._session.flush()
        return claim

    async def add_document(self, doc: ClaimDocument) -> ClaimDocument:
        self._session.add(doc)
        await self._session.flush()
        return doc

    async def set_extracted_fields(self, fields: ExtractedFields) -> ExtractedFields:
        self._session.add(fields)
        await self._session.flush()
        return fields
