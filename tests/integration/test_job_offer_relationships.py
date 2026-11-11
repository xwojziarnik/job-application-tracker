"""ORM relationships of ``JobOffer``: its company and its tags.

In async code SQLAlchemy cannot load a relationship lazily on first access (that would run
a query behind the scenes and fails with ``MissingGreenlet``). Both relationships are
therefore declared with ``lazy="raise"``: reading one that was not loaded explicitly
(``selectinload``/``joinedload``) raises a clear error instead, so a forgotten load shows up
in tests, not in production. Each test runs on its own migrated database (D-12).
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import joinedload, selectinload

from job_tracker.enums import OfferSource, Seniority, WorkMode
from job_tracker.models import Company, JobOffer, Tag

pytestmark: pytest.MarkDecorator = pytest.mark.integration


@pytest.fixture
async def engine(test_db_url: str) -> AsyncIterator[AsyncEngine]:
    """Engine for this test's migrated database, disposed so the database can be dropped."""
    engine = create_async_engine(make_url(test_db_url))
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Session on this test's migrated database."""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
async def company(session: AsyncSession) -> Company:
    company = Company(name="ACME")
    session.add(company)
    await session.commit()
    return company


def _offer(company: Company, tags: list[Tag] | None = None) -> JobOffer:
    """A new offer of ``company``, with ``tags`` set before it is first saved."""
    offer = JobOffer(
        company_id=company.id,
        title="Python Developer",
        url=f"https://justjoin.it/job-offer/{uuid.uuid4().hex}",
        source=OfferSource.JUSTJOINIT,
        seniority=Seniority.MID,
        work_mode=WorkMode.REMOTE,
    )
    if tags is not None:
        offer.tags = tags
    return offer


async def _reload(engine: AsyncEngine, offer_id: uuid.UUID, *options: Any) -> JobOffer:
    """The offer read again in a fresh session, with the given loader options only."""
    async with AsyncSession(engine, expire_on_commit=False) as fresh:
        offer = await fresh.scalar(
            select(JobOffer).where(JobOffer.id == offer_id).options(*options)
        )
    assert offer is not None
    return offer


# --- Loading ------------------------------------------------------------------------------


async def test_tags_set_on_a_new_offer_are_saved_as_links(
    session: AsyncSession, engine: AsyncEngine, company: Company
) -> None:
    offer = _offer(company, tags=[Tag(name="fastapi"), Tag(name="postgresql")])
    session.add(offer)
    await session.commit()

    stored = await _reload(engine, offer.id, selectinload(JobOffer.tags))

    assert {tag.name for tag in stored.tags} == {"fastapi", "postgresql"}
    assert await session.scalar(text("SELECT count(*) FROM job_offer_tags")) == 2


async def test_tags_are_loaded_in_alphabetical_order(
    session: AsyncSession, engine: AsyncEngine, company: Company
) -> None:
    # A stable order, so API responses do not change from one request to the next.
    names = ["sqlalchemy", "docker", "python", "aws"]
    offer = _offer(company, tags=[Tag(name=name) for name in names])
    session.add(offer)
    await session.commit()

    stored = await _reload(engine, offer.id, selectinload(JobOffer.tags))

    assert [tag.name for tag in stored.tags] == sorted(names)


async def test_offer_without_tags_has_an_empty_list(
    session: AsyncSession, engine: AsyncEngine, company: Company
) -> None:
    offer = _offer(company)
    session.add(offer)
    await session.commit()

    stored = await _reload(engine, offer.id, selectinload(JobOffer.tags))

    assert stored.tags == []


async def test_one_tag_can_be_shared_by_several_offers(
    session: AsyncSession, engine: AsyncEngine, company: Company
) -> None:
    fastapi = Tag(name="fastapi")
    first, second = _offer(company, tags=[fastapi]), _offer(company, tags=[fastapi])
    session.add_all([first, second])
    await session.commit()

    assert await session.scalar(text("SELECT count(*) FROM tags")) == 1
    assert (await _reload(engine, second.id, selectinload(JobOffer.tags))).tags[0].id == fastapi.id


async def test_company_is_loaded_with_the_offer(
    session: AsyncSession, engine: AsyncEngine, company: Company
) -> None:
    offer = _offer(company)
    session.add(offer)
    await session.commit()

    stored = await _reload(engine, offer.id, joinedload(JobOffer.company))

    assert stored.company.id == company.id
    assert stored.company.name == "ACME"


# --- lazy="raise" -------------------------------------------------------------------------


async def test_reading_tags_that_were_not_loaded_raises(
    session: AsyncSession, engine: AsyncEngine, company: Company
) -> None:
    offer = _offer(company)
    session.add(offer)
    await session.commit()

    stored = await _reload(engine, offer.id)

    with pytest.raises(InvalidRequestError, match="lazy='raise'"):
        _ = stored.tags


async def test_reading_the_company_that_was_not_loaded_raises(
    session: AsyncSession, engine: AsyncEngine, company: Company
) -> None:
    offer = _offer(company)
    session.add(offer)
    await session.commit()

    stored = await _reload(engine, offer.id)

    with pytest.raises(InvalidRequestError, match="lazy='raise'"):
        _ = stored.company


# --- Changing and deleting ----------------------------------------------------------------


async def test_replacing_the_tags_of_a_loaded_offer_updates_the_links(
    session: AsyncSession, engine: AsyncEngine, company: Company
) -> None:
    offer = _offer(company, tags=[Tag(name="django"), Tag(name="python")])
    session.add(offer)
    await session.commit()

    async with AsyncSession(engine, expire_on_commit=False) as other:
        loaded = await other.scalar(
            select(JobOffer).where(JobOffer.id == offer.id).options(selectinload(JobOffer.tags))
        )
        assert loaded is not None
        python = next(tag for tag in loaded.tags if tag.name == "python")
        loaded.tags = [python, Tag(name="fastapi")]
        await other.commit()

    stored = await _reload(engine, offer.id, selectinload(JobOffer.tags))

    assert [tag.name for tag in stored.tags] == ["fastapi", "python"]
    # The tag removed from the offer is kept (tags are shared, D-09).
    assert await session.scalar(text("SELECT count(*) FROM tags")) == 3


async def test_deleting_an_offer_whose_tags_were_not_loaded_removes_its_links(
    session: AsyncSession, engine: AsyncEngine, company: Company
) -> None:
    # passive_deletes: the database removes the links (ON DELETE CASCADE), so SQLAlchemy
    # does not need to load the collection, which lazy="raise" would refuse.
    offer = _offer(company, tags=[Tag(name="fastapi")])
    session.add(offer)
    await session.commit()

    async with AsyncSession(engine) as other:
        loaded = await other.get(JobOffer, offer.id)
        assert loaded is not None
        await other.delete(loaded)
        await other.commit()

    assert await session.scalar(text("SELECT count(*) FROM job_offer_tags")) == 0
    assert await session.scalar(text("SELECT count(*) FROM tags")) == 1
