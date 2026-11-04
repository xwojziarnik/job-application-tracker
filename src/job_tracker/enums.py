"""Closed sets of values shared by the models, the schemas and the API.

Each value is the string stored in the database (``VARCHAR`` with a ``CHECK``, D-02) and
sent in the API, so changing, adding or removing one needs a migration and a decision
entry. Members are ``StrEnum``, so ``WorkMode.REMOTE == "remote"``.
"""

from enum import StrEnum


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
