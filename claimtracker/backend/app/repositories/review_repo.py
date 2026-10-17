"""
app/repositories/review_repo.py
─────────────────────────────────
"""
from typing import List
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.review import Review
from app.repositories.base import BaseRepository


class ReviewRepository(BaseRepository[Review]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Review, session)

    async def list_for_claim(self, claim_id: UUID) -> List[Review]:
        result = await self._session.execute(
            select(Review).where(Review.claim_id == claim_id).order_by(Review.reviewed_at.desc())
        )
        return list(result.scalars().all())
