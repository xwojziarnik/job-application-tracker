"""Request and response schemas of a job offer (decisions: "Job offer", D-03, D-05, D-09).

Every rule is defined once, as an ``Annotated`` field type, and shared by the create and
update schemas. URLs and tags are stored normalised (``normalise_offer_url``,
``normalise_tag_name``), so the unique constraints and tag filters see one spelling.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from job_tracker.core.salary import ensure_valid_salary
from job_tracker.core.tags import MAX_TAGS_PER_OFFER, normalise_tag_name
from job_tracker.core.urls import normalise_offer_url
from job_tracker.enums import Currency, OfferSource, Seniority, WorkMode
from job_tracker.schemas.company import CompanySummary
from job_tracker.utils import BLANK_TO_NONE, require_https_url

# "Today" for the posting date is the owner's calendar day, not the server's (D-11): a
# container runs in UTC, where shortly after midnight in Poland it is still yesterday.
LOCAL_TIMEZONE: ZoneInfo = ZoneInfo("Europe/Warsaw")


def ensure_not_in_future(posted_on: date) -> date:
    """Return ``posted_on``, or raise ``ValueError`` if it is after today in Poland."""
    today = datetime.now(tz=LOCAL_TIMEZONE).date()
    if posted_on > today:
        raise ValueError("Posting date must not be in the future")
    return posted_on


def merge_duplicate_tags(tags: list[str]) -> list[str]:
    """Return ``tags`` without repeated names, keeping the first occurrence of each.

    Runs after every name has been normalised, so ``FastAPI`` and ``fastapi`` count as one.
    """
    return list(dict.fromkeys(tags))


OfferTitle = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=200,
    ),
]

OfferUrl = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        max_length=2048,
    ),
    AfterValidator(require_https_url),
    AfterValidator(normalise_offer_url),
]

OfferLocation = Annotated[
    Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None, BLANK_TO_NONE
]

# A fragment of the title to search for; blank means no search.
OfferSearch = Annotated[
    Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None, BLANK_TO_NONE
]

OfferDescription = Annotated[
    Annotated[str, StringConstraints(strip_whitespace=True, max_length=20_000)] | None,
    BLANK_TO_NONE,
]

OfferNotes = Annotated[
    Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None, BLANK_TO_NONE
]

SalaryAmount = Annotated[int, Field(gt=0)]

PostedOn = Annotated[date, AfterValidator(ensure_not_in_future)]

TagName = Annotated[str, AfterValidator(normalise_tag_name)]

# The limit applies to the list as sent, before duplicates are merged.
TagList = Annotated[
    list[TagName], Field(max_length=MAX_TAGS_PER_OFFER), AfterValidator(merge_duplicate_tags)
]


class JobOfferCreate(BaseModel):
    """A new job offer, as sent by the client (decisions: "Job offer").

    Whether the company exists and is active is checked by the service (404 / 409), as the
    schema has no access to the database. Unknown fields, such as ``id`` or the timestamps,
    are rejected.
    """

    company_id: UUID
    title: OfferTitle
    url: OfferUrl
    source: OfferSource
    seniority: Seniority
    work_mode: WorkMode
    location: OfferLocation = None
    salary_min: SalaryAmount | None = None
    salary_max: SalaryAmount | None = None
    currency: Currency | None = None
    posted_on: PostedOn | None = None
    description: OfferDescription = None
    notes: OfferNotes = None
    tags: TagList = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def check_salary(self) -> Self:
        """Require the whole salary or none of it, with the minimum not above the maximum.

        ``salary_min``, ``salary_max`` and ``currency`` are set together or not at all (D-03),
        the same rule as ``ck_job_offers_salary_range`` in the database; positive amounts are
        already checked by ``SalaryAmount``.
        """
        ensure_valid_salary(self.salary_min, self.salary_max, self.currency)
        return self


class JobOfferUpdate(BaseModel):
    """Changes to a job offer (PATCH): only the fields the client sends.

    An omitted field is not changed (``model_dump(exclude_unset=True)``); ``null`` clears an
    optional field and is rejected for the required ones and for ``tags`` (``[]`` removes
    all tags). ``company_id`` is not accepted: an offer never moves to another company.
    Whether the salary is complete after the change depends on the stored values, so the
    service checks it; this schema only checks the order of the amounts sent together.
    """

    title: OfferTitle | None = None
    url: OfferUrl | None = None
    source: OfferSource | None = None
    seniority: Seniority | None = None
    work_mode: WorkMode | None = None
    location: OfferLocation | None = None
    salary_min: SalaryAmount | None = None
    salary_max: SalaryAmount | None = None
    currency: Currency | None = None
    posted_on: PostedOn | None = None
    description: OfferDescription | None = None
    notes: OfferNotes | None = None
    tags: TagList | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("title", "url", "source", "seniority", "work_mode", "tags", mode="before")
    @classmethod
    def reject_null(cls, value: object) -> object:
        """Reject an explicit ``null`` for fields that cannot be cleared.

        Pydantic does not validate defaults, so this runs only for fields the client sends.
        """
        if value is None:
            raise ValueError("Must not be null")
        return value

    @model_validator(mode="after")
    def check_salary_order(self) -> Self:
        """Reject a minimum above the maximum when both amounts are sent."""
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("salary_min must not be greater than salary_max")
        return self


class JobOfferRead(BaseModel):
    """A job offer as returned by the API, built from the ORM model (``from_attributes``).

    Fields use plain types, not the input types above: the data was validated when it was
    saved, and a rule such as "not in the future" must not make a stored offer unreadable
    later. ``tags`` are names, sorted by the relationship; the ``tags`` relationship must be
    loaded (``selectinload``), as reading it otherwise raises (``lazy="raise"``).
    """

    id: UUID
    company: CompanySummary
    title: str
    url: str
    source: OfferSource
    seniority: Seniority
    work_mode: WorkMode
    location: str | None
    salary_min: int | None
    salary_max: int | None
    currency: Currency | None
    posted_on: date | None
    description: str | None
    notes: str | None
    tags: list[str]
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

    @field_validator("tags", mode="before")
    @classmethod
    def tag_names(cls, value: object) -> object:
        """Turn ``Tag`` objects into their names; names given as text are kept."""
        if isinstance(value, list):
            return sorted(
                [element.name if hasattr(element, "name") else element for element in value]
            )
        return value


class JobOfferSort(StrEnum):
    """Sort orders of the offer list (D-21); every order ends with ``id``, so pages are stable."""

    NEWEST = "newest"
    SALARY = "salary"
    TITLE = "title"


class JobOfferFilters(BaseModel):
    """Query parameters of ``GET /job-offers`` (D-21), all optional and combined with AND.

    Repeatable ``work_mode`` and ``source`` match any of the given values; repeatable
    ``tag`` requires all of them (names normalised like stored tags). ``seniority`` also
    matches the combined values containing the level. ``min_salary`` and ``currency`` are
    given together. Offers of inactive companies are left out unless ``include_inactive``.
    """

    company_id: UUID | None = None
    work_mode: list[WorkMode] = Field(default_factory=list)
    seniority: Seniority | None = None
    tag: TagList = Field(default_factory=list)
    min_salary: SalaryAmount | None = None
    currency: Currency | None = None
    source: list[OfferSource] = Field(default_factory=list)
    search: OfferSearch = None
    include_inactive: bool = False
    sort: JobOfferSort = JobOfferSort.NEWEST

    @model_validator(mode="after")
    def check_salary_filter(self) -> Self:
        """Require ``min_salary`` and ``currency`` together: an amount means nothing
        without its currency, and a currency alone filters nothing."""
        if (self.min_salary is None) != (self.currency is None):
            raise ValueError("min_salary and currency must be given together")
        return self
