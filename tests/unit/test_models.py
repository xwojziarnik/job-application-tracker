"""Every model is registered in ``Base.metadata``, which Alembic compares with the database."""

from job_tracker.models import Base, Company, JobOffer


def test_company_table_is_registered() -> None:
    assert Base.metadata.tables["companies"] is Company.__table__


def test_job_offer_table_is_registered() -> None:
    assert Base.metadata.tables["job_offers"] is JobOffer.__table__
