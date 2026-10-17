"""
app/api/handbooks.py
─────────────────────
Admin uploads a handbook PDF; it's chunked, embedded, and stored in FAISS.
"""
from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_current_user, require_admin, CurrentUser
from app.schemas.handbook import HandbookListResponse, HandbookResponse
from app.services.handbook_service import HandbookService

router = APIRouter(prefix="/handbooks", tags=["handbooks"])


@router.post("", response_model=HandbookResponse, status_code=status.HTTP_201_CREATED)
async def upload_handbook(
    version_tag: str = Form(..., description="e.g. 'v2024-01'"),
    handbook_file: UploadFile = File(..., description="Policy handbook PDF"),
    current_user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a new policy handbook.
    Chunks it (1000 chars, 200 overlap), embeds with sentence-transformers,
    stores in FAISS, and marks this version as active.
    """
    svc = HandbookService(db)
    return await svc.ingest(
        file=handbook_file,
        version_tag=version_tag,
        uploaded_by=current_user.user_id,
    )


@router.get("", response_model=HandbookListResponse)
async def list_handbooks(
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    svc = HandbookService(db)
    return await svc.list_handbooks()
