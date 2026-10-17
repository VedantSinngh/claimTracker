"""
app/api/analytics.py
─────────────────────
Analytics summary endpoint backed by analytics.sql queries.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_admin, CurrentUser
from app.schemas.analytics import AnalyticsSummaryResponse
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=AnalyticsSummaryResponse)
async def analytics_summary(
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
):
    """Return aggregated analytics data for the admin dashboard."""
    svc = AnalyticsService(db)
    return await svc.get_summary()
