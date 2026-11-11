"""Request and response schemas of a company (decisions: "Company").

The rules of each field are defined once, as an ``Annotated`` type, and shared by the
create and update schemas: text is trimmed, blank optional text becomes ``None``, and
lengths match the columns of the ``companies`` table.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    StringConstraints,
    field_validator,
)

from job_tracker.utils import BLANK_TO_NONE, require_https_url

CompanyName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200, min_length=1)]
CompanyNotes = Annotated[
    Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None, BLANK_TO_NONE
]
CompanyLocation = Annotated[
    Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None, BLANK_TO_NONE
]
CompanyIndustry = Annotated[
    Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None, BLANK_TO_NONE
]
CompanyWebsite = Annotated[
    Annotated[str, StringConstraints(max_length=2048), AfterValidator(require_https_url)] | None,
    BLANK_TO_NONE,
]


class CompanyCreate(BaseModel):
    """A new company, as sent by the client; a new company is always active."""

    name: CompanyName
    notes: CompanyNotes = None
    location: CompanyLocation = None
    industry: CompanyIndustry = None
    website: CompanyWebsite = None

    model_config = ConfigDict(extra="forbid")


class CompanyUpdate(BaseModel):
    """Changes to a company (PATCH): only the fields sent; ``null`` clears optional ones."""

    name: CompanyName | None = None
    notes: CompanyNotes = None
    location: CompanyLocation = None
    industry: CompanyIndustry = None
    website: CompanyWebsite = None
    is_active: bool | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("name", "is_active", mode="before")
    @classmethod
    def ensure_value_is_not_none(cls, value: object) -> object:
        """Reject an explicit ``null`` for fields that cannot be cleared.

        Pydantic does not validate defaults, so this runs only when the client sends the
        field; an omitted field stays unset and is not changed (``exclude_unset``).
        """
        if value is None:
            raise ValueError("Must not be null")
        return value


class CompanyRead(BaseModel):
    """A company as returned by the API, built from the ORM model."""

    id: UUID
    name: str
    notes: str | None
    location: str | None
    industry: str | None
    website: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CompanySummary(BaseModel):
    """The company of a job offer as shown in offer responses (D-21).

    Enough to show which company an offer belongs to without a second request; the full
    company is under ``/companies/{company_id}``.
    """

    id: UUID
    name: str
    is_active: bool
    model_config = ConfigDict(from_attributes=True)
