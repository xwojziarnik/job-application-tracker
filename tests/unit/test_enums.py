"""Allowed values of the enumerations (D-02, D-14, D-15, D-16, D-20).

The values are the strings stored in the database and sent in the API, so changing one
needs a migration (the ``CHECK`` constraint) and is a change of the API.
"""

from enum import StrEnum

import pytest

from job_tracker.enums import ApplicationStatus, Currency, OfferSource, Seniority, WorkMode


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
        (
            ApplicationStatus,
            [
                "draft",
                "applied",
                "screening",
                "technical",
                "task",
                "final",
                "offer",
                "on_hold",
                "accepted",
                "rejected",
                "withdrawn",
                "ghosted",
            ],
        ),
    ],
    ids=["offer-source", "seniority", "work-mode", "currency", "application-status"],
)
def test_enum_has_exactly_the_decided_values(enum: type[StrEnum], values: list[str]) -> None:
    assert [member.value for member in enum] == values


@pytest.mark.parametrize("enum", [OfferSource, Seniority, WorkMode, Currency, ApplicationStatus])
def test_enum_members_are_strings(enum: type[StrEnum]) -> None:
    # StrEnum members compare equal to their values, e.g. WorkMode.REMOTE == "remote".
    assert issubclass(enum, StrEnum)


# --- ApplicationStatus: active and final statuses (D-06, D-16) ----------------------------

FINAL_STATUSES: list[ApplicationStatus] = [
    ApplicationStatus.ACCEPTED,
    ApplicationStatus.REJECTED,
    ApplicationStatus.WITHDRAWN,
    ApplicationStatus.GHOSTED,
]


def test_final_statuses_are_the_decided_ones() -> None:
    # The partial unique index of applications is built from this list (D-06).
    assert ApplicationStatus.final() == FINAL_STATUSES


@pytest.mark.parametrize("status", list(ApplicationStatus))
def test_a_status_is_final_exactly_when_it_ends_the_recruitment(
    status: ApplicationStatus,
) -> None:
    assert status.is_final is (status in FINAL_STATUSES)


def test_on_hold_is_active() -> None:
    # A paused recruitment can continue, so it blocks a second application (D-16).
    assert ApplicationStatus.ON_HOLD.is_final is False
