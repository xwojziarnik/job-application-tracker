"""Company use cases (D-04, D-05, D-07, D-10).

Each method is one use case and one transaction: the service commits, and turns database
errors into domain errors, so endpoints never see ``None`` or ``IntegrityError``.
"""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from job_tracker.core.exceptions import (
    CompanyAlreadyExistsError,
    CompanyInactiveError,
    NotFoundError,
)
from job_tracker.db.errors import violated_constraint
from job_tracker.models.company import Company
from job_tracker.repositories.company import CompanyRepository
from job_tracker.schemas.company import CompanyCreate, CompanyUpdate

# Unique index on lower(name) from the companies migration; violating it means a duplicate.
UNIQUE_NAME_INDEX = "uq_companies_lower_name"


class CompanyService:
    """Company use cases working in one session, typically one per request."""

    def __init__(self, session: AsyncSession) -> None:
        self.session: AsyncSession = session
        self.repository: CompanyRepository = CompanyRepository(session)

    async def create_company(self, data: CompanyCreate) -> Company:
        """Create and commit a company.

        Raises ``CompanyAlreadyExistsError`` (409) when the name is taken regardless of
        case; the transaction is rolled back first, so the session stays usable.
        """
        company = Company(**data.model_dump())
        try:
            await self.repository.add_company(company)
        except IntegrityError as exc:
            await self.session.rollback()
            if violated_constraint(exc) == UNIQUE_NAME_INDEX:
                raise CompanyAlreadyExistsError() from exc
            raise
        await self.session.commit()
        return company

    async def get_company(self, company_id: UUID) -> Company:
        """Return the company with ``company_id``, active or not.

        Raises ``NotFoundError`` (404) when there is no such company.
        """
        result = await self.repository.get_company(company_id)
        if result is None:
            raise NotFoundError(f"Company with ID {company_id} not found")
        return result

    async def list_companies(
        self, *, limit: int, offset: int, search: str | None = None, include_inactive: bool = False
    ) -> tuple[list[Company], int]:
        """Return one page of companies and the total; see ``CompanyRepository``."""
        return await self.repository.list_companies(
            limit=limit, offset=offset, search=search, include_inactive=include_inactive
        )

    async def update_company(self, company_id: UUID, data: CompanyUpdate) -> Company:
        """Apply the fields set in ``data`` to the company and commit.

        Omitted fields are not changed (``exclude_unset``). Raises ``NotFoundError`` (404)
        for an unknown company and ``CompanyAlreadyExistsError`` (409) when the new name
        belongs to another company.
        """
        company = await self.get_company(company_id)
        try:
            await self.repository.update_company(company, data.model_dump(exclude_unset=True))
        except IntegrityError as exc:
            await self.session.rollback()
            if violated_constraint(exc) == UNIQUE_NAME_INDEX:
                raise CompanyAlreadyExistsError() from exc
            raise
        await self.session.commit()
        return company

    async def get_or_create_company(self, data: CompanyCreate) -> tuple[Company, bool]:
        """Return the company with this name, or create it; the flag says if it was created.

        An existing company is returned unchanged (the other fields in ``data`` are
        ignored); an inactive one is refused with ``CompanyInactiveError`` (409) and never
        reactivated (D-10). The insert runs in a savepoint: if another request commits the
        same name between the lookup and the insert, the unique index rejects the insert,
        only the savepoint is rolled back, and that company is returned instead (D-05).
        """
        company = await self.repository.get_by_name(data.name)
        if company is None:
            try:
                async with self.session.begin_nested():
                    company = await self.repository.add_company(Company(**data.model_dump()))
            except IntegrityError as exc:
                if violated_constraint(exc) != UNIQUE_NAME_INDEX:
                    raise
                company = await self.repository.get_by_name(data.name)
            else:
                await self.session.commit()
                return company, True
        if company is None or not company.is_active:
            raise CompanyInactiveError(f"Company with name {data.name} is inactive")
        return company, False
