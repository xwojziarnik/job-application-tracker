"""``JobOfferRepository``: database access for job offers and their tags (D-07, D-09).

The repository adds, changes and deletes, and flushes, but never commits: the service
decides when to commit. Offers are read with their company and tags loaded, because both
relationships refuse lazy loading (``lazy="raise"``). Tags are created with
``INSERT ... ON CONFLICT DO NOTHING``, so a name another request has just stored is not an
error. Committed data is checked from a second session, which sees only committed rows.
Each test runs on its own migrated database (D-12).
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from job_tracker.enums import OfferSource, Seniority, WorkMode
from job_tracker.models import Company, JobOffer, Tag
from job_tracker.repositories.job_offer import JobOfferRepository

pytestmark: pytest.MarkDecorator = pytest.mark.integration


@pytest.fixture
async def engine(test_db_url: str) -> AsyncIterator[AsyncEngine]:
    """Engine for this test's migrated database, disposed so the database can be dropped."""
    engine = create_async_engine(make_url(test_db_url))
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """The session the repository works in, as in one request."""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def repository(session: AsyncSession) -> JobOfferRepository:
    return JobOfferRepository(session)


@pytest.fixture
async def company(session: AsyncSession) -> Company:
    company = Company(name="ACME")
    session.add(company)
    await session.commit()
    return company


def _offer(company: Company, slug: str = "python-developer", **fields: object) -> JobOffer:
    values: dict[str, object] = {
        "company_id": company.id,
        "title": "Python Developer",
        "url": f"https://justjoin.it/job-offer/{slug}",
        "source": OfferSource.JUSTJOINIT,
        "seniority": Seniority.MID,
        "work_mode": WorkMode.REMOTE,
    }
    return JobOffer(**(values | fields))


async def _committed_count(engine: AsyncEngine, table: str) -> int:
    """Rows of ``table`` visible to another session, i.e. committed ones."""
    async with AsyncSession(engine) as other:
        # Table names come from this module only, never from outside input.
        result = await other.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
    return int(result or 0)


async def _committed_tag_names(engine: AsyncEngine) -> list[str]:
    async with AsyncSession(engine) as other:
        return list((await other.scalars(select(Tag.name).order_by(Tag.name))).all())


# --- add_offer ----------------------------------------------------------------------------


async def test_add_offer_flushes_without_committing(
    repository: JobOfferRepository, session: AsyncSession, engine: AsyncEngine, company: Company
) -> None:
    offer = await repository.add_offer(_offer(company))

    assert isinstance(offer.id, uuid.UUID)
    assert offer.created_at is not None
    assert await _committed_count(engine, "job_offers") == 0

    await session.commit()
    assert await _committed_count(engine, "job_offers") == 1


async def test_add_offer_saves_its_tags(
    repository: JobOfferRepository, session: AsyncSession, engine: AsyncEngine, company: Company
) -> None:
    tags = await repository.get_or_create_tags(["fastapi", "python"])
    offer = _offer(company)
    offer.tags = tags

    await repository.add_offer(offer)
    await session.commit()

    assert await _committed_count(engine, "job_offer_tags") == 2


async def test_rolled_back_offer_is_not_stored(
    repository: JobOfferRepository, session: AsyncSession, engine: AsyncEngine, company: Company
) -> None:
    await repository.add_offer(_offer(company))
    await session.rollback()

    assert await _committed_count(engine, "job_offers") == 0


# --- get_offer ----------------------------------------------------------------------------


async def test_get_offer_returns_it_with_company_and_tags_loaded(
    repository: JobOfferRepository, session: AsyncSession, engine: AsyncEngine, company: Company
) -> None:
    offer = _offer(company)
    offer.tags = await repository.get_or_create_tags(["python", "aws", "fastapi"])
    await repository.add_offer(offer)
    await session.commit()

    async with AsyncSession(engine, expire_on_commit=False) as fresh:
        stored = await JobOfferRepository(fresh).get_offer(offer.id)

    # Read after the session is closed: works only if both were loaded by the query.
    assert stored is not None
    assert stored.company.name == "ACME"
    assert [tag.name for tag in stored.tags] == ["aws", "fastapi", "python"]


async def test_get_offer_returns_an_offer_without_tags(
    repository: JobOfferRepository, session: AsyncSession, engine: AsyncEngine, company: Company
) -> None:
    offer = await repository.add_offer(_offer(company))
    await session.commit()

    async with AsyncSession(engine, expire_on_commit=False) as fresh:
        stored = await JobOfferRepository(fresh).get_offer(offer.id)

    assert stored is not None
    assert stored.tags == []


async def test_get_offer_returns_none_for_an_unknown_id(repository: JobOfferRepository) -> None:
    assert await repository.get_offer(uuid.uuid4()) is None


# --- get_or_create_tags -------------------------------------------------------------------


async def test_missing_tags_are_created_without_committing(
    repository: JobOfferRepository, session: AsyncSession, engine: AsyncEngine
) -> None:
    tags = await repository.get_or_create_tags(["fastapi", "python"])

    assert [tag.name for tag in tags] == ["fastapi", "python"]
    assert all(isinstance(tag.id, uuid.UUID) for tag in tags)
    assert await _committed_count(engine, "tags") == 0

    await session.commit()
    assert await _committed_tag_names(engine) == ["fastapi", "python"]


async def test_existing_tags_are_reused(
    repository: JobOfferRepository, session: AsyncSession, engine: AsyncEngine
) -> None:
    [first] = await repository.get_or_create_tags(["fastapi"])
    await session.commit()

    [again] = await repository.get_or_create_tags(["fastapi"])
    await session.commit()

    assert again.id == first.id
    assert await _committed_count(engine, "tags") == 1


async def test_tag_stored_by_another_session_is_reused_without_error(
    repository: JobOfferRepository, session: AsyncSession, engine: AsyncEngine
) -> None:
    # Another request has just committed the same name: ON CONFLICT DO NOTHING skips it
    # instead of raising, and the existing row is returned.
    async with AsyncSession(engine, expire_on_commit=False) as other:
        existing = Tag(name="fastapi")
        other.add(existing)
        await other.commit()
        existing_id = existing.id

    tags = await repository.get_or_create_tags(["fastapi", "python"])
    await session.commit()

    assert [tag.name for tag in tags] == ["fastapi", "python"]
    assert tags[0].id == existing_id
    assert await _committed_count(engine, "tags") == 2


async def test_tags_are_returned_in_the_order_of_the_names(
    repository: JobOfferRepository, session: AsyncSession
) -> None:
    await repository.get_or_create_tags(["python"])
    await session.commit()

    tags = await repository.get_or_create_tags(["sql", "python", "aws"])

    assert [tag.name for tag in tags] == ["sql", "python", "aws"]


async def test_no_names_give_no_tags(repository: JobOfferRepository, engine: AsyncEngine) -> None:
    assert await repository.get_or_create_tags([]) == []
    assert await _committed_count(engine, "tags") == 0


# --- update_offer -------------------------------------------------------------------------


async def test_update_offer_sets_the_fields_and_flushes(
    repository: JobOfferRepository, session: AsyncSession, engine: AsyncEngine, company: Company
) -> None:
    offer = await repository.add_offer(_offer(company))
    await session.commit()
    created_updated_at = offer.updated_at

    await repository.update_offer(offer, {"title": "Senior Python Developer", "location": None})

    assert offer.title == "Senior Python Developer"
    assert offer.updated_at > created_updated_at
    await session.commit()
    async with AsyncSession(engine) as other:
        assert await other.scalar(select(JobOffer.title)) == "Senior Python Developer"


async def test_update_offer_replaces_the_tags(
    repository: JobOfferRepository, session: AsyncSession, engine: AsyncEngine, company: Company
) -> None:
    offer = _offer(company)
    offer.tags = await repository.get_or_create_tags(["django", "python"])
    await repository.add_offer(offer)
    await session.commit()

    loaded = await repository.get_offer(offer.id)
    assert loaded is not None
    await repository.update_offer(
        loaded, {"tags": await repository.get_or_create_tags(["python", "fastapi"])}
    )
    await session.commit()

    async with AsyncSession(engine, expire_on_commit=False) as fresh:
        stored = await JobOfferRepository(fresh).get_offer(offer.id)
    assert stored is not None
    assert [tag.name for tag in stored.tags] == ["fastapi", "python"]
    # The tag removed from the offer stays: tags are shared (D-09).
    assert await _committed_tag_names(engine) == ["django", "fastapi", "python"]


# --- delete_offer -------------------------------------------------------------------------


async def test_delete_offer_removes_it_and_its_links_but_keeps_the_tags(
    repository: JobOfferRepository, session: AsyncSession, engine: AsyncEngine, company: Company
) -> None:
    offer = _offer(company)
    offer.tags = await repository.get_or_create_tags(["fastapi"])
    await repository.add_offer(offer)
    await session.commit()

    async with AsyncSession(engine) as other:
        other_repository = JobOfferRepository(other)
        loaded = await other_repository.get_offer(offer.id)
        assert loaded is not None
        await other_repository.delete_offer(loaded)
        assert await other.scalar(select(func.count()).select_from(JobOffer)) == 0
        await other.commit()

    assert await _committed_count(engine, "job_offers") == 0
    assert await _committed_count(engine, "job_offer_tags") == 0
    assert await _committed_tag_names(engine) == ["fastapi"]
