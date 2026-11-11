"""Building blocks shared by the request schemas (companies, job offers).

Each schema defines its fields as ``Annotated`` types; the parts that repeat across schemas
live here, so a rule such as "blank optional text is stored as ``None``" is written once.
"""

from typing import Annotated

from pydantic import (
    AnyUrl,
    BeforeValidator,
    TypeAdapter,
    UrlConstraints,
    ValidationError,
)


def blank_to_none(value: str | None) -> str | None:
    """Trim text and turn blank text into ``None``; leave other values to the type check.

    Runs before the type and length checks (``BeforeValidator``), so ``"  "`` never
    reaches them as text and "no value" has a single representation.
    """
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


# Put after the optional type of a field: ``Annotated[<text> | None, BLANK_TO_NONE]``.
BLANK_TO_NONE: BeforeValidator = BeforeValidator(blank_to_none)

# Validates a URL without changing it; used by ``require_https_url``.
HTTPS_URL: TypeAdapter[AnyUrl] = TypeAdapter(
    Annotated[AnyUrl, UrlConstraints(allowed_schemes=["https"], host_required=True)]
)


def require_https_url(value: str) -> str:
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
