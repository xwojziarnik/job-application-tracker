"""The ``applications`` table (decisions: "Application").

Rules the database enforces on its own, also for rows written outside the application:
the status and the currency are ``VARCHAR`` columns with a ``CHECK`` listing their values
(D-02, D-16), a draft has no sent date, the expected salary is all or nothing (D-03), an
offer has at most one active application (D-06) and deleting an offer deletes its
applications (D-04).
"""

from datetime import date
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, Enum, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from job_tracker.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_values
from job_tracker.enums import ApplicationStatus, Currency

# Rows the "one active application per offer" index applies to (D-06), built from the
# single list of final statuses: "status NOT IN ('accepted', 'rejected', ...)".
_FINAL_VALUES: str = ", ".join(f"'{status.value}'" for status in ApplicationStatus.final())
ACTIVE_ONLY: str = f"status NOT IN ({_FINAL_VALUES})"

# A draft has not been sent, so it has no sent date; other statuses may lack one too
# (the date of an old application may be unknown).
DRAFT_NOT_SENT: str = "status <> 'draft' OR sent_on IS NULL"

# The expected salary is all or nothing (D-03): no amount at all, or a positive amount
# with its currency.
NO_EXPECTED_SALARY: str = "expected_salary IS NULL AND currency IS NULL"
COMPLETE_EXPECTED_SALARY: str = (
    "expected_salary IS NOT NULL AND currency IS NOT NULL AND expected_salary > 0"
)


class Application(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The owner's application to a job offer (decisions: "Application").

    An offer can have many applications over time, but at most one active one
    (``uq_applications_active_job_offer_id``, D-06). ``job_offer_id`` cannot change after
    the application is created; in stage 2 neither can the status. The expected salary
    follows the convention of offers: B2B net per month in whole currency units (D-03).
    """

    __tablename__ = "applications"

    __table_args__ = (
        CheckConstraint(DRAFT_NOT_SENT, name="draft_not_sent"),
        CheckConstraint(
            f"({NO_EXPECTED_SALARY}) OR ({COMPLETE_EXPECTED_SALARY})", name="expected_salary"
        ),
        # A partial index covers only active applications; the service maps a violation
        # to 409 application_already_active. It does not serve every lookup by offer, so
        # job_offer_id has its own index as well (ON DELETE CASCADE).
        Index(
            "uq_applications_active_job_offer_id",
            "job_offer_id",
            unique=True,
            postgresql_where=text(ACTIVE_ONLY),
        ),
    )

    job_offer_id: Mapped[UUID] = mapped_column(
        ForeignKey("job_offers.id", ondelete="CASCADE"), index=True
    )
    # Default set by the application only: a row written with plain SQL must name its status.
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(
            ApplicationStatus,
            length=20,
            native_enum=False,
            create_constraint=True,
            name="status",
            values_callable=enum_values,
        ),
        default=ApplicationStatus.APPLIED,
    )
    sent_on: Mapped[date | None] = mapped_column(Date())
    expected_salary: Mapped[int | None] = mapped_column()
    currency: Mapped[Currency | None] = mapped_column(
        Enum(
            Currency,
            length=10,
            native_enum=False,
            create_constraint=True,
            name="currency",
            values_callable=enum_values,
        )
    )
    notes: Mapped[str | None] = mapped_column(String(2000))
