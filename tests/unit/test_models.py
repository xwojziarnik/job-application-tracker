"""Every model is registered in ``Base.metadata``, which Alembic compares with the database."""

from job_tracker.models import Base, Company


def test_company_table_is_registered() -> None:
    assert Base.metadata.tables["companies"] is Company.__table__
