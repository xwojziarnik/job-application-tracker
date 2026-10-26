"""SQLAlchemy models.

Import every model module here, so `Base.metadata` is complete for Alembic.
"""

from job_tracker.db.base import Base

__all__ = ["Base"]
