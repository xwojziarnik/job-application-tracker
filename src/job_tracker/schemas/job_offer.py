"""Request and response schemas of a job offer (decisions: "Job offer", D-03, D-05, D-09).

Every rule is defined once, as an ``Annotated`` field type, and shared by the create and
update schemas. URLs and tags are stored normalised (``normalise_offer_url``,
``normalise_tag_name``), so the unique constraints and tag filters see one spelling.
"""

from datetime import date, datetime
from typing import Annotated, Self
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from job_tracker.core.tags import MAX_TAGS_PER_OFFER, normalise_tag_name
from job_tracker.core.urls import normalise_offer_url
from job_tracker.enums import Currency, OfferSource, Seniority, WorkMode
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
        provided = [
            field
            for field in (self.salary_min, self.salary_max, self.currency)
            if field is not None
        ]

        if 0 < len(provided) < 3:
            raise ValueError("salary_min, salary_max and currency must be set together")
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("salary_min must not be greater than salary_max")

        return self
