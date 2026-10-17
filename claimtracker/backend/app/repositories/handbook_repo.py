"""
app/repositories/handbook_repo.py
───────────────────────────────────
"""
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.handbook import HandbookVersion
from app.repositories.base import BaseRepository


class HandbookRepository(BaseRepository[HandbookVersion]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(HandbookVersion, session)

    async def get_active(self) -> Optional[HandbookVersion]:
        result = await self._session.execute(
            select(HandbookVersion).where(HandbookVersion.is_active == True)  # noqa: E712
        )
        return result.scalar_one_or_none()

    async def deactivate_all(self) -> None:
        await self._session.execute(
            update(HandbookVersion).values(is_active=False)
        )

    async def activate(self, handbook_id) -> None:
        await self.deactivate_all()
        hb = await self.get_by_id(handbook_id)
        if hb:
            hb.is_active = True  # type: ignore[assignment]
        await self._session.flush()
