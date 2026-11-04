"""Allowed values of the enumerations (D-02, D-14, D-15, D-20).

The values are the strings stored in the database and sent in the API, so changing one
needs a migration (the ``CHECK`` constraint) and is a change of the API.
"""

from enum import StrEnum

import pytest

from job_tracker.enums import Currency, OfferSource, Seniority, WorkMode


@pytest.mark.parametrize(
    ("enum", "values"),
    [
        (
            OfferSource,
            [
                "linkedin",
                "pracuj",
                "justjoinit",
                "bulldogjob",
                "nofluffjobs",
                "rocketjobs",
                "joobie",
                "company_website",
            ],
        ),
        (
            Seniority,
            ["junior", "junior_mid", "mid", "mid_senior", "senior", "senior_lead", "lead"],
        ),
        (WorkMode, ["remote", "hybrid", "office"]),
        (Currency, ["PLN", "EUR", "USD"]),
    ],
    ids=["offer-source", "seniority", "work-mode", "currency"],
)
def test_enum_has_exactly_the_decided_values(enum: type[StrEnum], values: list[str]) -> None:
    assert [member.value for member in enum] == values


@pytest.mark.parametrize("enum", [OfferSource, Seniority, WorkMode, Currency])
def test_enum_members_are_strings(enum: type[StrEnum]) -> None:
    # StrEnum members compare equal to their values, e.g. WorkMode.REMOTE == "remote".
    assert issubclass(enum, StrEnum)
