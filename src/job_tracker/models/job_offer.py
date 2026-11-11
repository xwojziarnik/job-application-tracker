"""The ``job_offers`` table (decisions: "Job offer").

Rules the database enforces on its own, also for rows written outside the application:
the enumerations are ``VARCHAR`` columns with a ``CHECK`` listing their values (D-02), the
salary is all or nothing (D-03), the URL is unique (D-05) and a company with offers cannot
be deleted (D-04).
"""

from datetime import date
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from job_tracker.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from job_tracker.enums import Currency, OfferSource, Seniority, WorkMode
from job_tracker.models.company import Company
from job_tracker.models.tag import Tag, job_offer_tags

# The salary is all or nothing (decisions: "Job offer", D-03): either no salary at all, or a
# complete range with its currency, positive and ordered.
NO_SALARY: str = "salary_min IS NULL AND salary_max IS NULL AND currency IS NULL"
COMPLETE_SALARY: str = (
    "salary_min IS NOT NULL AND salary_max IS NOT NULL AND currency IS NOT NULL"
    " AND salary_min > 0 AND salary_min <= salary_max"
)


def _enum_values(enum_class: type[StrEnum]) -> list[str]:
    """Return the values of ``enum_class``, e.g. ``["remote", "hybrid", "office"]``.

    Passed as ``values_callable`` to SQLAlchemy's ``Enum``, so the database stores and
    checks the values (``"mid_senior"``) instead of the member names (``"MID_SENIOR"``),
    which SQLAlchemy uses by default (D-02).
    """
    return [e.value for e in enum_class]


class JobOffer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A job offer published by a company (decisions: "Job offer").

    The salary is a B2B net amount per month in whole currency units (D-03); an hourly
    rate is converted when the offer is entered. ``company_id`` cannot change after the
    offer is created. ``uq_job_offers_url`` compares URLs as stored: the application
    normalises a URL before saving it, so the same offer under a different spelling is
    also caught (D-05).
    """

    __tablename__ = "job_offers"

    __table_args__ = (
        CheckConstraint(f"({NO_SALARY}) OR ({COMPLETE_SALARY})", name="salary_range"),
    )

    # Indexed: PostgreSQL does not index foreign keys, and the offers of a company are
    # filtered by it (and checked by RESTRICT when a company is deleted).
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), index=True
    )
    # Relationships are never loaded implicitly: in async code a lazy load would run a hidden
    # query and fail with MissingGreenlet. lazy="raise" turns a forgotten load into a clear
    # error; load them explicitly with joinedload(JobOffer.company) and
    # selectinload(JobOffer.tags).
    company: Mapped[Company] = relationship(lazy="raise")
    # Tags in alphabetical order, so responses are stable. Assigning a new list adds and
    # removes rows in job_offer_tags; removed tags stay in the tags table (they are shared).
    # passive_deletes: deleting an offer leaves the links to ON DELETE CASCADE, so the
    # collection does not have to be loaded first (lazy="raise" would refuse).
    tags: Mapped[list[Tag]] = relationship(
        secondary=job_offer_tags,
        lazy="raise",
        order_by=Tag.name,
        passive_deletes=True,
    )
    url: Mapped[str] = mapped_column(String(2048), unique=True)
    source: Mapped[OfferSource] = mapped_column(
        Enum(
            OfferSource,
            length=20,
            native_enum=False,
            create_constraint=True,
            name="source",
            values_callable=_enum_values,
        )
    )
    seniority: Mapped[Seniority] = mapped_column(
        Enum(
            Seniority,
            length=20,
            native_enum=False,
            create_constraint=True,
            name="seniority",
            values_callable=_enum_values,
        )
    )
    work_mode: Mapped[WorkMode] = mapped_column(
        Enum(
            WorkMode,
            length=20,
            native_enum=False,
            create_constraint=True,
            name="work_mode",
            values_callable=_enum_values,
        )
    )
    salary_min: Mapped[int | None] = mapped_column()
    salary_max: Mapped[int | None] = mapped_column()
    currency: Mapped[Currency | None] = mapped_column(
        Enum(
            Currency,
            length=10,
            native_enum=False,
            create_constraint=True,
            name="currency",
            values_callable=_enum_values,
        )
    )
    posted_on: Mapped[date | None] = mapped_column(Date())
    title: Mapped[str] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(20000))
    notes: Mapped[str | None] = mapped_column(String(2000))
