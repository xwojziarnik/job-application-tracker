"""Database access for companies (D-07).

The repository adds and flushes but never commits: each service method is one use case
and one transaction, and the service decides when to commit. Constraint violations (e.g. a
duplicate name) are left to the caller as ``IntegrityError``.
"""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from job_tracker.models.company import Company


class CompanyRepository:
    """Queries and writes for the ``companies`` table within the caller's session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session: AsyncSession = session

    async def add_company(self, company: Company) -> Company:
        """Add ``company`` and flush, so its ID is set and constraints are checked now."""
        self.session.add(company)
        await self.session.flush()
        return company

    async def get_company(self, company_id: UUID) -> Company | None:
        """Return the company with ``company_id``, active or not, or ``None``."""
        result = await self.session.get(Company, company_id)
        return result

    async def get_by_name(self, name: str) -> Company | None:
        """Return the company with ``name`` regardless of case, active or not, or ``None``.

        Inactive companies are included, so "get or create" can refuse them (D-10).
        """
        result = await self.session.scalar(
            select(Company).where(func.lower(Company.name) == name.lower())
        )
        return result

    async def list_companies(
        self, *, limit: int, offset: int, search: str | None = None, include_inactive: bool = False
    ) -> tuple[list[Company], int]:
        """Return one page of companies sorted by name regardless of case, and the total.

        Inactive companies are left out unless ``include_inactive`` is set (D-04);
        ``search`` matches a fragment of the name regardless of case, with ``%`` and ``_``
        taken literally. ``total`` counts every matching company, not only this page.
        """
        query = select(Company)
        if search:
            query = query.where(Company.name.icontains(search, autoescape=True))
        if not include_inactive:
            query = query.where(Company.is_active)
        total_count = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        result = await self.session.scalars(
            query.order_by(func.lower(Company.name)).limit(limit).offset(offset)
        )
        return list(result.all()), total_count or 0

    async def update_company(self, company: Company, changes: Mapping[str, Any]) -> Company:
        """Set the given fields on ``company`` and flush.

        ``changes`` holds only the fields to change, e.g. ``model_dump(exclude_unset=True)``
        of an update schema. ``updated_at`` is set by the database and loaded back right
        away (``eager_defaults`` in ``TimestampMixin``).
        """
        for key, value in changes.items():
            setattr(company, key, value)
        await self.session.flush()
        return company
