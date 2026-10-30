from sqlalchemy import String, true
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import Index
from sqlalchemy.sql import func

from job_tracker.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Company(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A company that posts job offers (decisions: "Company").

    Companies are never deleted, only deactivated with ``is_active`` (D-04). The name is
    unique regardless of case through ``uq_companies_lower_name`` (D-05).
    """

    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(200))
    website: Mapped[str | None] = mapped_column(String(2048))
    is_active: Mapped[bool] = mapped_column(server_default=true())
    location: Mapped[str | None] = mapped_column(String(200))
    industry: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(String(2000))


# Defined after the class: in the class body ``name`` is not a column yet. The name is
# explicit, because the naming convention cannot name an index on an expression, and the
# service maps this name to 409 Conflict (D-07).
Index("uq_companies_lower_name", func.lower(Company.name), unique=True)
