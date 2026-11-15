"""Closed sets of values shared by the models, the schemas and the API.

Each value is the string stored in the database (``VARCHAR`` with a ``CHECK``, D-02) and
sent in the API, so changing, adding or removing one needs a migration and a decision
entry. Members are ``StrEnum``, so ``WorkMode.REMOTE == "remote"``.
"""

from enum import StrEnum
from typing import Self


class OfferSource(StrEnum):
    """Where an offer was found: a job board or the company's careers page (D-20)."""

    LINKEDIN = "linkedin"
    PRACUJPL = "pracuj"
    JUSTJOINIT = "justjoinit"
    BULLDOGJOB = "bulldogjob"
    NOFLUFFJOBS = "nofluffjobs"
    ROCKETJOBS = "rocketjobs"
    JOOBIE = "joobie"
    COMPANY_WEBSITE = "company_website"


class Seniority(StrEnum):
    """Seniority as published in the offer: one level or two adjacent ones (D-15).

    Combined values such as ``mid_senior`` (job boards' "Mid/Senior") include both
    levels: filtering by ``mid`` must also match ``junior_mid`` and ``mid_senior``.
    """

    JUNIOR = "junior"
    JUNIOR_MID = "junior_mid"
    MID = "mid"
    MID_SENIOR = "mid_senior"
    SENIOR = "senior"
    SENIOR_LEAD = "senior_lead"
    LEAD = "lead"

    def matching(self) -> list[Self]:
        """Return the values an offer may have to match this level, in enum order (D-21).

        A value matches when it contains every level of this one: ``mid`` matches
        ``junior_mid``, ``mid`` and ``mid_senior``; a combined value matches only itself.
        """
        levels: set[str] = set(self.value.split("_"))
        return [s for s in Seniority if levels.issubset(s.value.split("_"))]


class WorkMode(StrEnum):
    """Where the work is done (D-14)."""

    REMOTE = "remote"
    HYBRID = "hybrid"
    OFFICE = "office"


class Currency(StrEnum):
    """Currency of a salary, as an ISO 4217 code (upper-case by definition, D-14)."""

    PLN = "PLN"
    EUR = "EUR"
    USD = "USD"


class ApplicationStatus(StrEnum):
    """Stage of an application: eight active statuses, then four final ones (D-16).

    An application is active while its status is not final; an offer can have at most one
    active application (D-06). ``on_hold`` is active: a paused recruitment can continue.
    """

    DRAFT = "draft"
    APPLIED = "applied"
    SCREENING = "screening"
    TECHNICAL = "technical"
    TASK = "task"
    FINAL = "final"
    OFFER = "offer"
    ON_HOLD = "on_hold"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    GHOSTED = "ghosted"

    @classmethod
    def final(cls) -> list[Self]:
        """Return the statuses that end a recruitment, in enum order (D-16).

        The only list of final statuses: the partial unique index of ``applications``
        (one active application per offer, D-06) is built from it, so changing it needs a
        migration.
        """
        return [cls.ACCEPTED, cls.REJECTED, cls.WITHDRAWN, cls.GHOSTED]

    @property
    def is_final(self) -> bool:
        """Whether this status ends the recruitment (see ``final``)."""
        return self in self.final()
