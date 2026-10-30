"""Shared model building blocks from ``db/base.py``.

``UUIDPrimaryKeyMixin`` gives a model a UUID primary key (D-01). The tests map it on a
throwaway declarative base, so no test table ends up in the application's metadata.
"""

import uuid

from sqlalchemy import String, Uuid
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.schema import CreateTable

from job_tracker.db.base import UUIDPrimaryKeyMixin


class ScratchBase(DeclarativeBase):
    pass


class Thing(UUIDPrimaryKeyMixin, ScratchBase):
    __tablename__ = "things"

    name: Mapped[str] = mapped_column(String(50))


def test_id_is_a_uuid_primary_key() -> None:
    column = Thing.__table__.c.id

    assert column.primary_key
    assert not column.nullable
    assert isinstance(column.type, Uuid)


def test_id_has_no_index_besides_the_primary_key() -> None:
    # The primary key constraint is already backed by a unique index.
    assert Thing.__table__.indexes == set()


def test_id_is_a_native_uuid_column_in_postgresql() -> None:
    ddl = str(CreateTable(Thing.__table__).compile(dialect=postgresql.dialect()))

    assert "id UUID NOT NULL" in ddl


def test_id_is_generated_by_the_application_not_the_database() -> None:
    column = Thing.__table__.c.id

    assert column.default is not None
    assert column.server_default is None


def test_id_is_not_assigned_before_flush() -> None:
    # The default runs when the row is inserted; code that needs the ID earlier sets it.
    assert Thing(name="draft").id is None
    explicit = uuid.uuid4()
    assert Thing(id=explicit, name="draft").id == explicit
