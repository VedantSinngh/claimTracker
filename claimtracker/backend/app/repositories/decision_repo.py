"""
app/repositories/decision_repo.py
───────────────────────────────────
"""
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision import Decision
from app.repositories.base import BaseRepository


class DecisionRepository(BaseRepository[Decision]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Decision, session)

    async def get_latest_for_claim(self, claim_id: UUID) -> Optional[Decision]:
        result = await self._session.execute(
            select(Decision)
            .where(Decision.claim_id == claim_id)
            .order_by(Decision.decided_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
