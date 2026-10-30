"""Migrations are numbered in order: ``001``, ``002``, ... (revision ID and file name).

The numbering only works with a single line of migrations: two branches that each add a
migration get the same number, and the second one must be renumbered before merging.
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import Script, ScriptDirectory


def _revisions(alembic_ini: Path) -> list[Script]:
    """All migrations from the first to the latest."""
    script_directory = ScriptDirectory.from_config(Config(str(alembic_ini)))
    return list(reversed(list(script_directory.walk_revisions())))


def test_there_is_a_single_head(alembic_ini: Path) -> None:
    heads = ScriptDirectory.from_config(Config(str(alembic_ini))).get_heads()

    assert len(heads) == 1


def test_revision_ids_are_consecutive_numbers(alembic_ini: Path) -> None:
    revisions = _revisions(alembic_ini)

    assert [r.revision for r in revisions] == [f"{n:03d}" for n in range(1, len(revisions) + 1)]


def test_each_migration_follows_the_previous_one(alembic_ini: Path) -> None:
    revisions = _revisions(alembic_ini)
    previous: list[str | None] = [None, *(r.revision for r in revisions[:-1])]

    assert [r.down_revision for r in revisions] == previous


def test_file_name_starts_with_the_revision_id(alembic_ini: Path) -> None:
    for revision in _revisions(alembic_ini):
        assert Path(revision.path).name.startswith(f"{revision.revision}_")
