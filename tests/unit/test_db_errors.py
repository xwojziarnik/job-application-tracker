"""``violated_constraint`` without a database: errors that carry no constraint name."""

from sqlalchemy.exc import IntegrityError

from job_tracker.db.errors import violated_constraint


def test_error_without_a_driver_cause_has_no_constraint() -> None:
    error = IntegrityError("INSERT INTO things ...", {}, Exception("not from asyncpg"))

    assert violated_constraint(error) is None
