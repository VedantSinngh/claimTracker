"""
app/models/__init__.py
───────────────────────
Import all models so Alembic's env.py sees them when it does
`from app.models import Base`.
"""
from app.models.base import Base  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.claim import Claim, ClaimDocument, ExtractedFields  # noqa: F401
from app.models.decision import Decision  # noqa: F401
from app.models.review import Review  # noqa: F401
from app.models.exclusion import Exclusion  # noqa: F401
from app.models.handbook import HandbookVersion  # noqa: F401
from app.models.audit_log import AuditLog  # noqa: F401

__all__ = [
    "Base",
    "User",
    "Claim",
    "ClaimDocument",
    "ExtractedFields",
    "Decision",
    "Review",
    "Exclusion",
    "HandbookVersion",
    "AuditLog",
]
