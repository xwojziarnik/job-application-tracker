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
    AnyUrl,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    StringConstraints,
    TypeAdapter,
    UrlConstraints,
    ValidationError,
    field_validator,
)


def _blank_to_none(value: str | None) -> str | None:
    """Trim text and turn blank text into ``None``; leave other values to the type check.

    Runs before the type and length checks (``BeforeValidator``), so ``"  "`` never
    reaches them as text and "no value" has a single representation.
    """
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


BlankToNone = BeforeValidator(_blank_to_none)

HTTPS_URL = TypeAdapter(
    Annotated[AnyUrl, UrlConstraints(allowed_schemes=["https"], host_required=True)]
)


def _require_https_url(value: str) -> str:
    """Check that ``value`` is an ``https`` URL with a host and return it unchanged.

    The URL is only validated, not normalised: ``HttpUrl``/``AnyUrl`` would add a trailing
    slash to ``https://acme.com``. The ``ValidationError`` of the URL type is replaced by a
    ``ValueError``, which Pydantic reports as an error of this field.
    """
    try:
        HTTPS_URL.validate_python(value)
    except ValidationError:
        raise ValueError("Must be an https URL") from None
    return value


CompanyName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200, min_length=1)]
CompanyNotes = Annotated[
    Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None, BlankToNone
]
CompanyLocation = Annotated[
    Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None, BlankToNone
]
CompanyIndustry = Annotated[
    Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None, BlankToNone
]
CompanyWebsite = Annotated[
    Annotated[str, StringConstraints(max_length=2048), AfterValidator(_require_https_url)] | None,
    BlankToNone,
]


class CompanyCreate(BaseModel):
    name: CompanyName
    notes: CompanyNotes = None
    location: CompanyLocation = None
    industry: CompanyIndustry = None
    website: CompanyWebsite = None

    model_config = ConfigDict(extra="forbid")


class CompanyUpdate(BaseModel):
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
