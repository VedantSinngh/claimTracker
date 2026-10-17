"""
app/repositories/exclusion_repo.py
────────────────────────────────────
ExclusionRepository — active exclusion list for the deterministic check.
"""
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exclusion import Exclusion
from app.repositories.base import BaseRepository


class ExclusionRepository(BaseRepository[Exclusion]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Exclusion, session)

    async def get_active_terms(self) -> List[str]:
        """Return all active exclusion terms for the validator."""
        result = await self._session.execute(
            select(Exclusion.term).where(Exclusion.is_active == True)  # noqa: E712
        )
        return list(result.scalars().all())

    async def get_by_term(self, term: str) -> Optional[Exclusion]:
        result = await self._session.execute(
            select(Exclusion).where(Exclusion.term == term)
        )
        return result.scalar_one_or_none()

    async def list_with_count(self, *, skip: int = 0, limit: int = 50) -> Tuple[List[Exclusion], int]:
        results = await self._session.execute(
            select(Exclusion).order_by(Exclusion.created_at.desc()).offset(skip).limit(limit)
        )
        count_result = await self._session.execute(select(func.count()).select_from(Exclusion))
        return list(results.scalars().all()), count_result.scalar_one()

    async def soft_delete(self, exclusion_id: UUID) -> bool:
        obj = await self.get_by_id(exclusion_id)
        if obj is None:
            return False
        obj.is_active = False  # type: ignore[assignment]
        await self._session.flush()
        return True
