"""Job offer use cases (D-03, D-04, D-05, D-07, D-09, D-10).

Each method is one use case and one transaction: the service commits, and turns missing
rows and database errors into domain errors, so endpoints never see ``None`` or
``IntegrityError``. A failed use case leaves nothing behind: checks that can fail come
before the first write, and a rejected write rolls back the tags created with it.
"""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from job_tracker.core.exceptions import (
    CompanyInactiveError,
    InvalidSalaryError,
    JobOfferAlreadyExistsError,
    NotFoundError,
)
from job_tracker.core.salary import ensure_valid_salary
from job_tracker.db.errors import violated_constraint
from job_tracker.models import JobOffer
from job_tracker.repositories.company import CompanyRepository
from job_tracker.repositories.job_offer import JobOfferRepository
from job_tracker.schemas.job_offer import JobOfferCreate, JobOfferUpdate

# Unique constraint on the normalised URL (naming convention uq_<table>_<column>);
# violating it means the offer is already stored (D-05).
UNIQUE_URL_CONSTRAINT: str = "uq_job_offers_url"


class JobOfferService:
    """Job offer use cases working in one session, typically one per request."""

    def __init__(self, session: AsyncSession) -> None:
        self.session: AsyncSession = session
        self.offers: JobOfferRepository = JobOfferRepository(session)
        self.companies: CompanyRepository = CompanyRepository(session)

    async def create_offer(self, data: JobOfferCreate) -> JobOffer:
        """Create and commit an offer with its tags, creating the missing tags.

        Raises ``NotFoundError`` (404) for an unknown company, ``CompanyInactiveError``
        (409) for an inactive one (D-10), both before anything is written, and
        ``JobOfferAlreadyExistsError`` (409) when the normalised URL is already stored.
        """
        company = await self.companies.get_company(data.company_id)
        if company is None:
            raise NotFoundError(f"Company with ID {data.company_id} not found")
        if not company.is_active:
            raise CompanyInactiveError("Company is inactive; activate it before adding offers")

        tags = await self.offers.get_or_create_tags(data.tags)

        offer = JobOffer(**data.model_dump(exclude={"tags"}), tags=tags)
        try:
            await self.offers.add_offer(offer)
        except IntegrityError as error:
            await self.session.rollback()
            if violated_constraint(error) == UNIQUE_URL_CONSTRAINT:
                raise JobOfferAlreadyExistsError() from error
            raise

        await self.session.commit()
        return offer

    async def get_offer(self, offer_id: UUID) -> JobOffer:
        """Return the offer with its company and tags loaded; ``NotFoundError`` (404) if none."""
        offer = await self.offers.get_offer(offer_id)
        if offer is None:
            raise NotFoundError(f"Job offer with ID {offer_id} not found")
        return offer

    async def update_offer(self, offer_id: UUID, data: JobOfferUpdate) -> JobOffer:
        """Apply the fields sent in ``data`` to the offer and commit.

        The salary is checked on the values after the change (sent values over stored
        ones; a key sent as ``null`` clears the stored value), before anything is written:
        ``InvalidSalaryError`` (422) if it would be incomplete or out of order. Tag names
        become ``Tag`` objects, created if missing. Raises ``NotFoundError`` (404) for an
        unknown offer and ``JobOfferAlreadyExistsError`` (409) for a URL of another offer.
        """
        offer = await self.get_offer(offer_id)
        changes = data.model_dump(exclude_unset=True)

        min_after = changes.get("salary_min", offer.salary_min)
        max_after = changes.get("salary_max", offer.salary_max)
        currency_after = changes.get("currency", offer.currency)

        try:
            ensure_valid_salary(min_after, max_after, currency_after)
        except ValueError as error:
            raise InvalidSalaryError(str(error)) from error

        if "tags" in changes:
            changes["tags"] = await self.offers.get_or_create_tags(changes["tags"])

        try:
            await self.offers.update_offer(offer, changes)
        except IntegrityError as error:
            await self.session.rollback()
            if violated_constraint(error) == UNIQUE_URL_CONSTRAINT:
                raise JobOfferAlreadyExistsError() from error
            raise

        await self.session.commit()
        return offer

    async def delete_offer(self, offer_id: UUID) -> None:
        """Delete the offer and commit; its tags stay. ``NotFoundError`` (404) if unknown."""
        offer = await self.get_offer(offer_id)
        await self.offers.delete_offer(offer)
        await self.session.commit()
