"""
app/repositories/role_repo.py
──────────────────────────────
RoleRepository — name lookup for the `roles` table.

Role rows are seeded by migration 0004 and effectively immutable at runtime,
so this repository is read-only apart from `get_or_create`, which exists for
test fixtures that build a schema with `create_all` instead of Alembic.
"""
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.role import Role
from app.repositories.base import BaseRepository


class RoleRepository(BaseRepository[Role]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Role, session)

    async def get_by_name(self, name: str) -> Optional[Role]:
        result = await self._session.execute(
            select(Role).where(Role.name == name)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> List[Role]:
        result = await self._session.execute(select(Role).order_by(Role.name))
        return list(result.scalars().all())

    async def get_or_create(self, name: str, description: Optional[str] = None) -> Role:
        """
        Fetch a role by name, inserting it if absent.
        Used by test fixtures; production rows come from migration 0004.
        """
        role = await self.get_by_name(name)
        if role is not None:
            return role
        role = Role(name=name, description=description)
        self._session.add(role)
        await self._session.flush()
        return role
