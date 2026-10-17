"""
app/models/base.py
───────────────────
Re-export Base so models only import from one place.
"""
from app.core.database import Base

__all__ = ["Base"]
