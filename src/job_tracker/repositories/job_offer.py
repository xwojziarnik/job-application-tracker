"""Database access for job offers and their tags (D-07, D-09).

The repository adds, changes and deletes, and flushes, but never commits: each service
method is one use case and one transaction, and the service decides when to commit, so an
offer and the tags created for it are saved or rolled back together. Constraint violations
(e.g. a URL stored twice) are left to the caller as ``IntegrityError``.
"""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from job_tracker.models import Company, JobOffer, Tag
from job_tracker.schemas.job_offer import JobOfferFilters, JobOfferSort

# How each sort order of the offer list translates into ORDER BY (D-21). The client picks a
# key, never a column. Missing dates and salaries go last (PostgreSQL puts NULL first in a
# descending order), and ``id`` breaks ties, so pages never repeat or skip offers (D-08).
SORT_ORDERS: dict[JobOfferSort, tuple[ColumnElement[Any], ...]] = {
    JobOfferSort.NEWEST: (
        JobOffer.posted_on.desc().nulls_last(),
        JobOffer.created_at.desc(),
        JobOffer.id.asc(),
    ),
    JobOfferSort.SALARY: (
        JobOffer.salary_max.desc().nulls_last(),
        JobOffer.id.asc(),
    ),
    JobOfferSort.TITLE: (
        func.lower(JobOffer.title).asc(),
        JobOffer.id.asc(),
    ),
}


class JobOfferRepository:
    """Queries and writes for ``job_offers`` and ``tags`` within the caller's session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session: AsyncSession = session

    async def add_offer(self, offer: JobOffer) -> JobOffer:
        """Add ``offer`` with any tags already set, and flush.

        After the flush the offer has its ID and timestamps, and the constraints are checked.
        """
        self.session.add(offer)
        await self.session.flush()
        return offer

    async def get_offer(self, offer_id: UUID) -> JobOffer | None:
        """Return the offer with ``offer_id`` with its company and tags loaded, or ``None``.

        Both relationships refuse lazy loading (``lazy="raise"``), so they are loaded by
        this query. ``select`` is used instead of ``session.get``, which may return an
        object already in the session without running the loaders.
        """
        query = (
            select(JobOffer)
            .where(JobOffer.id == offer_id)
            .options(joinedload(JobOffer.company), selectinload(JobOffer.tags))
        )
        return await self.session.scalar(query)

    async def get_or_create_tags(self, names: Sequence[str]) -> list[Tag]:
        """Return the tags with these names, creating the missing ones (not committed).

        ``names`` must already be normalised and unique (``JobOfferCreate``/``Update`` do
        that). All names are inserted with one ``INSERT ... ON CONFLICT DO NOTHING``, so a
        name stored meanwhile by another request is skipped instead of raising (D-09), and
        one ``SELECT`` then loads every tag as an ORM object. Tags are returned in the order
        of ``names``.
        """
        if not names:
            return []
        insertion = (
            insert(Tag)
            .values([{"id": uuid4(), "name": name} for name in names])
            .on_conflict_do_nothing(index_elements=["name"])
        )
        await self.session.execute(insertion)
        existing_tags = await self.session.scalars(select(Tag).where(Tag.name.in_(names)))
        by_name = {tag.name: tag for tag in existing_tags}
        return [by_name[name] for name in names]

    async def update_offer(self, offer: JobOffer, changes: Mapping[str, Any]) -> JobOffer:
        """Set the given fields on ``offer`` and flush.

        ``changes`` holds only the fields to change. ``tags`` must be ``Tag`` objects (from
        ``get_or_create_tags``), and ``offer`` must have been read with ``get_offer``: replacing
        the tags compares them with the loaded ones. ``updated_at`` is set by the database.
        """
        for key, value in changes.items():
            setattr(offer, key, value)
        await self.session.flush()
        return offer

    async def delete_offer(self, offer: JobOffer) -> None:
        """Delete ``offer`` and flush; the database removes its tag links (CASCADE)."""
        await self.session.delete(offer)
        await self.session.flush()

    async def list_offers(
        self, filters: JobOfferFilters, limit: int, offset: int
    ) -> tuple[list[JobOffer], int]:
        """Return one page of offers matching ``filters`` and the number of all matches.

        Every filter given adds a condition (AND). ``tag`` adds one ``EXISTS`` per name, so
        an offer must have all of them without multiplying rows; the company is joined only
        to leave out inactive ones. ``total`` is counted before sorting and paging; the page
        is loaded with its company and tags (``selectinload``, so ``LIMIT`` counts offers).
        """
        query = select(JobOffer)

        if not filters.include_inactive:
            query = query.join(JobOffer.company).where(Company.is_active)
        if filters.company_id:
            query = query.where(JobOffer.company_id == filters.company_id)
        if filters.work_mode:
            query = query.where(JobOffer.work_mode.in_(filters.work_mode))
        if filters.source:
            query = query.where(JobOffer.source.in_(filters.source))
        if filters.seniority:
            query = query.where(JobOffer.seniority.in_(filters.seniority.matching()))
        for name in filters.tag:
            query = query.where(JobOffer.tags.any(Tag.name == name))
        if filters.min_salary:
            query = query.where(
                JobOffer.salary_max >= filters.min_salary, JobOffer.currency == filters.currency
            )
        if filters.search:
            query = query.where(JobOffer.title.icontains(filters.search, autoescape=True))

        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))

        page = await self.session.scalars(
            query.order_by(*SORT_ORDERS[filters.sort])
            .limit(limit)
            .offset(offset)
            .options(joinedload(JobOffer.company), selectinload(JobOffer.tags))
        )
        return (list(page.all()), total or 0)

    async def list_tags(self, search: str | None, limit: int, offset: int) -> tuple[list[str], int]:
        """Return one page of tag names in alphabetical order and the number of all matches.

        ``search`` matches a fragment of the name; ``%`` and ``_`` are taken literally.
        """
        query = select(Tag.name)
        if search:
            query = query.where(Tag.name.icontains(search, autoescape=True))

        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        names = await self.session.scalars(query.order_by(Tag.name).limit(limit).offset(offset))
        return (list(names.all()), total or 0)
