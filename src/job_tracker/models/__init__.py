"""SQLAlchemy models.

Import every model module here, so `Base.metadata` is complete for Alembic.
"""

from job_tracker.db.base import Base
from job_tracker.models.company import Company
from job_tracker.models.job_offer import JobOffer
from job_tracker.models.tag import Tag, job_offer_tags

__all__ = ["Base", "Company", "JobOffer", "Tag", "job_offer_tags"]
