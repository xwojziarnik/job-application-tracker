"""Database access for job offers and their tags (D-07, D-09).

The repository adds, changes and deletes, and flushes, but never commits: each service
method is one use case and one transaction, and the service decides when to commit, so an
offer and the tags created for it are saved or rolled back together. Constraint violations
(e.g. a URL stored twice) are left to the caller as ``IntegrityError``.
"""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from job_tracker.models import JobOffer, Tag


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
