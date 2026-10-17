"""
app/repositories/base.py
─────────────────────────
Generic async repository base — provides common CRUD operations.
Subclass and specialise; never put SQL in services.
"""
from typing import Any, Generic, List, Optional, Type, TypeVar
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    def __init__(self, model: Type[ModelT], session: AsyncSession) -> None:
        self._model = model
        self._session = session

    async def get_by_id(self, record_id: UUID) -> Optional[ModelT]:
        result = await self._session.execute(
            select(self._model).where(self._model.id == record_id)  # type: ignore[attr-defined]
        )
        return result.scalar_one_or_none()

    async def get_all(self, *, skip: int = 0, limit: int = 20) -> List[ModelT]:
        result = await self._session.execute(
            select(self._model).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def count(self) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(self._model)
        )
        return result.scalar_one()

    async def create(self, obj: ModelT) -> ModelT:
        self._session.add(obj)
        await self._session.flush()
        await self._session.refresh(obj)
        return obj

    async def delete(self, record_id: UUID) -> bool:
        obj = await self.get_by_id(record_id)
        if obj is None:
            return False
        await self._session.delete(obj)
        await self._session.flush()
        return True

    async def save(self) -> None:
        await self._session.commit()
