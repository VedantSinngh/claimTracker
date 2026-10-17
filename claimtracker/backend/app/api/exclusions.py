"""
app/api/exclusions.py
──────────────────────
Admin-only CRUD for the exclusions list.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_admin, CurrentUser
from app.models.exclusion import Exclusion
from app.repositories.exclusion_repo import ExclusionRepository
from app.schemas.exclusion import ExclusionCreateRequest, ExclusionListResponse, ExclusionResponse

router = APIRouter(prefix="/exclusions", tags=["exclusions"])


@router.get("", response_model=ExclusionListResponse)
async def list_exclusions(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
):
    repo = ExclusionRepository(db)
    items, total = await repo.list_with_count(skip=skip, limit=limit)
    return ExclusionListResponse(items=items, total=total)


@router.post("", response_model=ExclusionResponse, status_code=status.HTTP_201_CREATED)
async def create_exclusion(
    body: ExclusionCreateRequest,
    current_user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = ExclusionRepository(db)
    existing = await repo.get_by_term(body.term)
    if existing:
        raise HTTPException(status_code=409, detail=f"Term '{body.term}' already exists.")
    exc = Exclusion(
        term=body.term,
        description=body.description,
        created_by=current_user.user_id,
    )
    exc = await repo.create(exc)
    await db.commit()
    return exc


@router.delete("/{exclusion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_exclusion(
    exclusion_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
):
    repo = ExclusionRepository(db)
    deleted = await repo.soft_delete(exclusion_id)
    await db.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Exclusion not found")
