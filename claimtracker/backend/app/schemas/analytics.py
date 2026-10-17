"""
app/schemas/analytics.py
─────────────────────────
"""
from typing import Any, Dict, List

from pydantic import BaseModel


class AnalyticsSummaryResponse(BaseModel):
    approval_rejection_by_month: List[Dict[str, Any]]
    top_rejection_reasons: List[Dict[str, Any]]
    avg_processing_time_by_status: List[Dict[str, Any]]
    claims_per_user: List[Dict[str, Any]]
