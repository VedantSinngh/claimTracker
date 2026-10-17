"""
app/services/analytics_service.py
───────────────────────────────────
Executes the analytics.sql queries and returns structured results.
All complex SQL lives in db/analytics.sql and is referenced here as
raw text queries for clarity and maintainability.
"""
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.analytics import AnalyticsSummaryResponse


class AnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _fetch(self, sql: str) -> List[Dict[str, Any]]:
        result = await self._session.execute(text(sql))
        rows = result.mappings().all()
        return [dict(row) for row in rows]

    async def get_summary(self) -> AnalyticsSummaryResponse:
        approval_rejection = await self._fetch("""
            SELECT
                DATE_TRUNC('month', created_at) AS month,
                status,
                COUNT(*) AS count
            FROM claims
            WHERE status IN ('ACCEPTED', 'REJECTED')
            GROUP BY 1, 2
            ORDER BY 1 DESC, 2
        """)

        top_rejections = await self._fetch("""
            SELECT
                reason,
                COUNT(*) AS rejection_count,
                RANK() OVER (ORDER BY COUNT(*) DESC) AS rank
            FROM claims
            WHERE status = 'REJECTED'
            GROUP BY reason
            ORDER BY rank
            LIMIT 5
        """)

        avg_processing_time = await self._fetch("""
            WITH processing_times AS (
                SELECT
                    status,
                    EXTRACT(EPOCH FROM (updated_at - created_at)) AS seconds
                FROM claims
                WHERE status IN ('ACCEPTED', 'REJECTED', 'NEEDS_REVIEW')
            )
            SELECT
                status,
                ROUND(AVG(seconds)::numeric, 2) AS avg_seconds
            FROM processing_times
            GROUP BY status
        """)

        claims_per_user = await self._fetch("""
            SELECT
                u.full_name,
                u.email,
                COUNT(c.id) AS total_claims,
                SUM(CASE WHEN c.status = 'ACCEPTED' THEN 1 ELSE 0 END) AS accepted,
                SUM(CASE WHEN c.status = 'REJECTED' THEN 1 ELSE 0 END) AS rejected
            FROM users u
            LEFT JOIN claims c ON c.user_id = u.id
            GROUP BY u.id, u.full_name, u.email
            ORDER BY total_claims DESC
            LIMIT 20
        """)

        return AnalyticsSummaryResponse(
            approval_rejection_by_month=approval_rejection,
            top_rejection_reasons=top_rejections,
            avg_processing_time_by_status=avg_processing_time,
            claims_per_user=claims_per_user,
        )
