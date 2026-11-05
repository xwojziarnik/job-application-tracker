"""The ``tags`` and ``job_offer_tags`` tables as created by the migrations (D-09).

A tag is a normalised name shared by any number of offers; ``job_offer_tags`` links them
(many to many). Each test runs on its own database cloned from the migrated template
(D-12). Links are written with plain SQL: these tests check the tables and their
constraints, not the ORM relationship, which comes with the offer repository.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from job_tracker.db.errors import violated_constraint
from job_tracker.enums import OfferSource, Seniority, WorkMode
from job_tracker.models import Base, Company, JobOffer, Tag

pytestmark: pytest.MarkDecorator = pytest.mark.integration

UNIQUE_NAME: str = "uq_tags_name"
NAME_FORMAT: str = "ck_tags_name_format"
LINK_PRIMARY_KEY: str = "pk_job_offer_tags"
LINK_TO_OFFER: str = "fk_job_offer_tags_job_offer_id_job_offers"
LINK_TO_TAG: str = "fk_job_offer_tags_tag_id_tags"
STRING_TOO_LONG: str = "22001"  # PostgreSQL error code string_data_right_truncation


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


async def _offer(session: AsyncSession, slug: str = "python-developer") -> JobOffer:
    """A committed offer of a committed company."""
    company = Company(name=f"ACME {slug}")
    session.add(company)
    await session.flush()
    offer = JobOffer(
        company_id=company.id,
        title="Python Developer",
        url=f"https://justjoin.it/job-offer/{slug}",
        source=OfferSource.JUSTJOINIT,
        seniority=Seniority.MID,
        work_mode=WorkMode.REMOTE,
    )
    session.add(offer)
    await session.commit()
    return offer


async def _tag(session: AsyncSession, name: str = "fastapi") -> Tag:
    tag = Tag(name=name)
    session.add(tag)
    await session.commit()
    return tag


async def _link(session: AsyncSession, offer_id: uuid.UUID, tag_id: uuid.UUID) -> None:
    await session.execute(
        text("INSERT INTO job_offer_tags (job_offer_id, tag_id) VALUES (:offer, :tag)"),
        {"offer": offer_id, "tag": tag_id},
    )


async def _count(session: AsyncSession, table: str) -> int:
    # Table names come from this module only, never from outside input.
    result = await session.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
    return int(result or 0)


def test_tables_are_registered() -> None:
    assert Base.metadata.tables["tags"] is Tag.__table__
    assert "job_offer_tags" in Base.metadata.tables


# --- tags ---------------------------------------------------------------------------------


async def test_new_tag_gets_id_and_timestamps(session: AsyncSession) -> None:
    tag = await _tag(session)
    await session.refresh(tag)

    assert isinstance(tag.id, uuid.UUID)
    assert tag.created_at.tzinfo is not None
    assert tag.updated_at.tzinfo is not None


async def test_the_same_name_cannot_be_stored_twice(session: AsyncSession) -> None:
    await _tag(session, "fastapi")

    session.add(Tag(name="fastapi"))
    with pytest.raises(IntegrityError) as excinfo:
        await session.flush()

    # "Get or create" relies on this constraint (INSERT ... ON CONFLICT DO NOTHING).
    assert violated_constraint(excinfo.value) == UNIQUE_NAME


async def test_name_is_required(session: AsyncSession) -> None:
    session.add(Tag(name=None))

    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.parametrize("name", ["c++", "c#", ".net", "node.js", "machine-learning", "python3"])
async def test_normalised_names_are_accepted(session: AsyncSession, name: str) -> None:
    await _tag(session, name)

    assert await _count(session, "tags") == 1


@pytest.mark.parametrize(
    "name",
    ["FastAPI", "machine learning", " fastapi", "c_sharp", "ci/cd", "łódź", "", "---", "."],
    ids=[
        "upper-case",
        "space",
        "leading-space",
        "underscore",
        "slash",
        "non-ascii",
        "empty",
        "only-hyphens",
        "only-a-dot",
    ],
)
async def test_database_rejects_a_name_that_is_not_normalised(
    session: AsyncSession, name: str
) -> None:
    # Defence in depth: the application normalises names (D-09), and the database refuses
    # anything else, also when a row is written with plain SQL.
    with pytest.raises(IntegrityError) as excinfo:
        await session.execute(
            text("INSERT INTO tags (id, name) VALUES (:id, :name)"),
            {"id": uuid.uuid4(), "name": name},
        )

    assert violated_constraint(excinfo.value) == NAME_FORMAT


async def test_name_at_the_length_limit_is_accepted(session: AsyncSession) -> None:
    await _tag(session, "a" * 50)

    assert await _count(session, "tags") == 1


async def test_name_longer_than_the_limit_is_rejected(session: AsyncSession) -> None:
    session.add(Tag(name="a" * 51))

    with pytest.raises(DBAPIError) as excinfo:
        await session.flush()

    assert excinfo.value.orig is not None
    assert getattr(excinfo.value.orig.__cause__, "sqlstate", None) == STRING_TOO_LONG


# --- job_offer_tags -----------------------------------------------------------------------


async def test_offer_can_have_many_tags_and_tag_many_offers(session: AsyncSession) -> None:
    first = await _offer(session, "first")
    second = await _offer(session, "second")
    fastapi = await _tag(session, "fastapi")
    postgres = await _tag(session, "postgresql")

    await _link(session, first.id, fastapi.id)
    await _link(session, first.id, postgres.id)
    await _link(session, second.id, fastapi.id)
    await session.commit()

    assert await _count(session, "job_offer_tags") == 3


async def test_the_same_link_cannot_be_stored_twice(session: AsyncSession) -> None:
    offer = await _offer(session)
    tag = await _tag(session)
    await _link(session, offer.id, tag.id)

    with pytest.raises(IntegrityError) as excinfo:
        await _link(session, offer.id, tag.id)

    assert violated_constraint(excinfo.value) == LINK_PRIMARY_KEY


async def test_link_to_an_unknown_offer_is_rejected(session: AsyncSession) -> None:
    tag = await _tag(session)

    with pytest.raises(IntegrityError) as excinfo:
        await _link(session, uuid.uuid4(), tag.id)

    assert violated_constraint(excinfo.value) == LINK_TO_OFFER


async def test_link_to_an_unknown_tag_is_rejected(session: AsyncSession) -> None:
    offer = await _offer(session)

    with pytest.raises(IntegrityError) as excinfo:
        await _link(session, offer.id, uuid.uuid4())

    assert violated_constraint(excinfo.value) == LINK_TO_TAG


async def test_deleting_an_offer_deletes_its_links_but_keeps_the_tags(
    session: AsyncSession,
) -> None:
    offer = await _offer(session)
    tag = await _tag(session)
    await _link(session, offer.id, tag.id)
    await session.commit()

    await session.execute(text("DELETE FROM job_offers WHERE id = :id"), {"id": offer.id})
    await session.commit()

    assert await _count(session, "job_offer_tags") == 0
    assert await _count(session, "tags") == 1


async def test_tag_used_by_an_offer_cannot_be_deleted(session: AsyncSession) -> None:
    offer = await _offer(session)
    tag = await _tag(session)
    await _link(session, offer.id, tag.id)
    await session.commit()

    with pytest.raises(IntegrityError) as excinfo:
        await session.execute(text("DELETE FROM tags WHERE id = :id"), {"id": tag.id})

    assert violated_constraint(excinfo.value) == LINK_TO_TAG
