"""``JobOfferService``: the job offer use cases (D-03, D-04, D-05, D-07, D-09, D-10).

Each method is one use case and one transaction: the service commits, and turns missing
rows and database errors into domain errors (unknown offer or company → 404, inactive
company → 409, URL stored twice → 409, incomplete salary after a change → 422). A failed
use case leaves nothing behind, not even the tags it created. Commits are checked from a
second session, which sees only committed data. Each test runs on its own database (D-12).
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import selectinload

from job_tracker.core.exceptions import (
    CompanyInactiveError,
    InvalidSalaryError,
    JobOfferAlreadyExistsError,
    NotFoundError,
)
from job_tracker.models import Company, JobOffer, Tag
from job_tracker.schemas.job_offer import JobOfferCreate, JobOfferRead, JobOfferUpdate
from job_tracker.services.job_offer import JobOfferService

pytestmark: pytest.MarkDecorator = pytest.mark.integration

SALARY: dict[str, Any] = {"salary_min": 18_000, "salary_max": 24_000, "currency": "PLN"}


@pytest.fixture
async def engine(test_db_url: str) -> AsyncIterator[AsyncEngine]:
    """Engine for this test's migrated database, disposed so the database can be dropped."""
    engine = create_async_engine(make_url(test_db_url))
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """The session the service works in, as in one request."""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def service(session: AsyncSession) -> JobOfferService:
    return JobOfferService(session)


async def _company(engine: AsyncEngine, name: str = "ACME", *, is_active: bool = True) -> uuid.UUID:
    """Commit a company from a separate session, as another request would; return its ID."""
    async with AsyncSession(engine, expire_on_commit=False) as other:
        company = Company(name=name, is_active=is_active)
        other.add(company)
        await other.commit()
        return company.id


def _create(company_id: uuid.UUID, slug: str = "python-developer", **fields: Any) -> JobOfferCreate:
    """Validated create schema, as the endpoint would pass it."""
    data: dict[str, Any] = {
        "company_id": str(company_id),
        "title": "Python Developer",
        "url": f"https://justjoin.it/job-offer/{slug}",
        "source": "justjoinit",
        "seniority": "mid",
        "work_mode": "remote",
    }
    return JobOfferCreate.model_validate(data | fields)


def _update(**fields: Any) -> JobOfferUpdate:
    """Validated update schema with only the given fields set."""
    return JobOfferUpdate.model_validate(fields)


async def _stored_offers(engine: AsyncEngine) -> list[JobOffer]:
    """Committed offers with their tags, read in a separate session."""
    async with AsyncSession(engine, expire_on_commit=False) as other:
        offers = await other.scalars(select(JobOffer).options(selectinload(JobOffer.tags)))
        return list(offers.all())


async def _stored_tag_names(engine: AsyncEngine) -> list[str]:
    async with AsyncSession(engine) as other:
        return list((await other.scalars(select(Tag.name).order_by(Tag.name))).all())


# --- create_offer -------------------------------------------------------------------------


async def test_create_commits_the_offer_with_its_tags(
    service: JobOfferService, engine: AsyncEngine
) -> None:
    company_id = await _company(engine)

    offer = await service.create_offer(
        _create(company_id, url="HTTPS://JustJoin.IT/job-offer/acme/", tags=["FastAPI", "python"])
    )

    [stored] = await _stored_offers(engine)
    assert stored.id == offer.id
    assert stored.company_id == company_id
    assert stored.url == "https://justjoin.it/job-offer/acme"
    assert [tag.name for tag in stored.tags] == ["fastapi", "python"]


async def test_created_offer_can_be_turned_into_the_response(
    service: JobOfferService, engine: AsyncEngine
) -> None:
    company_id = await _company(engine)

    offer = await service.create_offer(_create(company_id, tags=["python", "aws"], **SALARY))

    read = JobOfferRead.model_validate(offer)
    assert read.tags == ["aws", "python"]
    assert (read.salary_min, read.salary_max, read.currency) == (18_000, 24_000, "PLN")


async def test_create_reuses_existing_tags(service: JobOfferService, engine: AsyncEngine) -> None:
    company_id = await _company(engine)
    await service.create_offer(_create(company_id, "first", tags=["python"]))

    await service.create_offer(_create(company_id, "second", tags=["python", "django"]))

    assert await _stored_tag_names(engine) == ["django", "python"]


async def test_create_for_an_unknown_company_returns_404(
    service: JobOfferService, engine: AsyncEngine
) -> None:
    with pytest.raises(NotFoundError) as excinfo:
        await service.create_offer(_create(uuid.uuid4(), tags=["python"]))

    assert (excinfo.value.status_code, excinfo.value.code) == (404, "not_found")
    assert await _stored_offers(engine) == []
    assert await _stored_tag_names(engine) == []


async def test_create_for_an_inactive_company_returns_409(
    service: JobOfferService, engine: AsyncEngine
) -> None:
    company_id = await _company(engine, is_active=False)

    with pytest.raises(CompanyInactiveError) as excinfo:
        await service.create_offer(_create(company_id, tags=["python"]))

    assert (excinfo.value.status_code, excinfo.value.code) == (409, "company_inactive")
    assert await _stored_offers(engine) == []
    assert await _stored_tag_names(engine) == []


async def test_create_with_a_stored_url_returns_409_and_keeps_no_new_tags(
    service: JobOfferService, engine: AsyncEngine
) -> None:
    company_id = await _company(engine)
    await service.create_offer(_create(company_id, url="https://acme.com/jobs/1", tags=["python"]))

    with pytest.raises(JobOfferAlreadyExistsError) as excinfo:
        # The same offer under another spelling: normalised to the same URL (D-05).
        await service.create_offer(
            _create(company_id, url="HTTPS://Acme.com/jobs/1/?utm_source=x", tags=["docker"])
        )

    assert (excinfo.value.status_code, excinfo.value.code) == (409, "job_offer_already_exists")
    assert len(await _stored_offers(engine)) == 1
    # The tag created for the rejected offer was rolled back with it.
    assert await _stored_tag_names(engine) == ["python"]


async def test_service_is_usable_after_a_rejected_duplicate(
    service: JobOfferService, engine: AsyncEngine
) -> None:
    company_id = await _company(engine)
    await service.create_offer(_create(company_id, url="https://acme.com/jobs/1"))
    with pytest.raises(JobOfferAlreadyExistsError):
        await service.create_offer(_create(company_id, url="https://acme.com/jobs/1"))

    await service.create_offer(_create(company_id, url="https://acme.com/jobs/2"))

    assert len(await _stored_offers(engine)) == 2


# --- get_offer ----------------------------------------------------------------------------


async def test_get_returns_the_offer_with_company_and_tags(
    service: JobOfferService, engine: AsyncEngine
) -> None:
    company_id = await _company(engine)
    created = await service.create_offer(_create(company_id, tags=["python"]))

    async with AsyncSession(engine, expire_on_commit=False) as fresh:
        offer = await JobOfferService(fresh).get_offer(created.id)

    assert offer.company.name == "ACME"
    assert [tag.name for tag in offer.tags] == ["python"]


async def test_get_unknown_offer_returns_404(service: JobOfferService) -> None:
    with pytest.raises(NotFoundError) as excinfo:
        await service.get_offer(uuid.uuid4())

    assert excinfo.value.status_code == 404


# --- update_offer -------------------------------------------------------------------------


async def test_update_changes_only_the_fields_sent_and_commits(
    service: JobOfferService, engine: AsyncEngine
) -> None:
    company_id = await _company(engine)
    created = await service.create_offer(_create(company_id, location="Kraków", tags=["python"]))

    updated = await service.update_offer(created.id, _update(title="Senior Python Developer"))

    [stored] = await _stored_offers(engine)
    assert stored.title == updated.title == "Senior Python Developer"
    assert stored.location == "Kraków"
    assert [tag.name for tag in stored.tags] == ["python"]


async def test_update_replaces_the_tags(service: JobOfferService, engine: AsyncEngine) -> None:
    company_id = await _company(engine)
    created = await service.create_offer(_create(company_id, tags=["django", "python"]))

    updated = await service.update_offer(created.id, _update(tags=["FastAPI", "python"]))

    assert JobOfferRead.model_validate(updated).tags == ["fastapi", "python"]
    [stored] = await _stored_offers(engine)
    assert [tag.name for tag in stored.tags] == ["fastapi", "python"]


async def test_update_with_an_empty_tag_list_removes_all_tags(
    service: JobOfferService, engine: AsyncEngine
) -> None:
    company_id = await _company(engine)
    created = await service.create_offer(_create(company_id, tags=["python"]))

    await service.update_offer(created.id, _update(tags=[]))

    [stored] = await _stored_offers(engine)
    assert stored.tags == []
    assert await _stored_tag_names(engine) == ["python"]


async def test_update_may_change_one_amount_of_a_complete_salary(
    service: JobOfferService, engine: AsyncEngine
) -> None:
    company_id = await _company(engine)
    created = await service.create_offer(_create(company_id, **SALARY))

    await service.update_offer(created.id, _update(salary_max=30_000))

    [stored] = await _stored_offers(engine)
    assert (stored.salary_min, stored.salary_max, stored.currency) == (18_000, 30_000, "PLN")


async def test_update_may_add_a_complete_salary(
    service: JobOfferService, engine: AsyncEngine
) -> None:
    company_id = await _company(engine)
    created = await service.create_offer(_create(company_id))

    await service.update_offer(created.id, _update(**SALARY))

    [stored] = await _stored_offers(engine)
    assert (stored.salary_min, stored.salary_max, stored.currency) == (18_000, 24_000, "PLN")


async def test_update_may_clear_the_whole_salary(
    service: JobOfferService, engine: AsyncEngine
) -> None:
    company_id = await _company(engine)
    created = await service.create_offer(_create(company_id, **SALARY))

    await service.update_offer(created.id, _update(salary_min=None, salary_max=None, currency=None))

    [stored] = await _stored_offers(engine)
    assert (stored.salary_min, stored.salary_max, stored.currency) == (None, None, None)


@pytest.mark.parametrize(
    ("initial", "changes"),
    [
        ({}, {"salary_max": 30_000}),
        ({}, {"salary_min": 18_000, "salary_max": 24_000}),
        (SALARY, {"currency": None}),
        (SALARY, {"salary_min": None}),
        (SALARY, {"salary_min": 30_000}),
    ],
    ids=[
        "amount-without-salary",
        "range-without-currency",
        "currency-cleared",
        "minimum-cleared",
        "minimum-above-stored-maximum",
    ],
)
async def test_update_that_leaves_an_invalid_salary_returns_422_and_changes_nothing(
    service: JobOfferService,
    engine: AsyncEngine,
    initial: dict[str, Any],
    changes: dict[str, Any],
) -> None:
    company_id = await _company(engine)
    created = await service.create_offer(_create(company_id, **initial))

    with pytest.raises(InvalidSalaryError) as excinfo:
        await service.update_offer(created.id, _update(title="Changed", **changes))

    assert (excinfo.value.status_code, excinfo.value.code) == (422, "invalid_salary")
    [stored] = await _stored_offers(engine)
    assert stored.title == "Python Developer"
    assert stored.salary_max == initial.get("salary_max")


async def test_update_to_the_url_of_another_offer_returns_409(
    service: JobOfferService, engine: AsyncEngine
) -> None:
    company_id = await _company(engine)
    await service.create_offer(_create(company_id, url="https://acme.com/jobs/1"))
    second = await service.create_offer(_create(company_id, url="https://acme.com/jobs/2"))

    with pytest.raises(JobOfferAlreadyExistsError):
        await service.update_offer(second.id, _update(url="https://ACME.com/jobs/1/"))

    urls = sorted(offer.url for offer in await _stored_offers(engine))
    assert urls == ["https://acme.com/jobs/1", "https://acme.com/jobs/2"]


async def test_update_unknown_offer_returns_404(service: JobOfferService) -> None:
    with pytest.raises(NotFoundError):
        await service.update_offer(uuid.uuid4(), _update(title="Anything"))


# --- delete_offer -------------------------------------------------------------------------


async def test_delete_removes_the_offer_and_keeps_its_tags(
    service: JobOfferService, engine: AsyncEngine
) -> None:
    company_id = await _company(engine)
    created = await service.create_offer(_create(company_id, tags=["python"]))

    await service.delete_offer(created.id)

    assert await _stored_offers(engine) == []
    assert await _stored_tag_names(engine) == ["python"]


async def test_delete_unknown_offer_returns_404(service: JobOfferService) -> None:
    with pytest.raises(NotFoundError):
        await service.delete_offer(uuid.uuid4())
