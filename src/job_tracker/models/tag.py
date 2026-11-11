"""The ``tags`` and ``job_offer_tags`` tables (D-09, decisions: "Tag").

A tag is a normalised name shared by any number of offers; ``job_offer_tags`` links offers
and tags (many to many). The database enforces the tag name rules on its own, with the
same constants as ``normalise_tag_name``, so the two cannot drift apart.
"""

from sqlalchemy import CheckConstraint, Column, ForeignKey, String, Table
from sqlalchemy.orm import Mapped, mapped_column

from job_tracker.core.tags import LETTER_OR_DIGIT, MAX_TAG_LENGTH, TAG_NAME_CHARACTERS
from job_tracker.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# PostgreSQL regular expressions (``~`` is case-sensitive): the whole name is made of the
# allowed characters, and it contains at least one letter or digit. ``TAG_NAME_CHARACTERS``
# is the body of a character class, ``LETTER_OR_DIGIT`` already a complete class.
TAG_NAME_FORMAT: str = f"name ~ '^[{TAG_NAME_CHARACTERS}]+$' AND name ~ '{LETTER_OR_DIGIT}'"


class Tag(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A tag such as ``fastapi`` or ``c++`` (decisions: "Tag").

    ``name`` is stored already normalised (``normalise_tag_name``) and is unique
    (``uq_tags_name``), which "get or create" relies on (``INSERT ... ON CONFLICT DO
    NOTHING``, D-09). ``ck_tags_name_format`` rejects names that are not normalised, also
    for rows written outside the application. Tags are not deleted through the API.
    """

    __tablename__ = "tags"
    __table_args__ = (CheckConstraint(TAG_NAME_FORMAT, name="name_format"),)

    name: Mapped[str] = mapped_column(String(MAX_TAG_LENGTH), unique=True)


# Links between offers and tags. A plain table, not a model: it has no columns of its own.
# The composite primary key allows a tag on an offer only once. Deleting an offer deletes
# its links (CASCADE) and keeps the tags; a tag used by an offer cannot be deleted (RESTRICT).
# The primary key also serves lookups by job_offer_id; tag_id has its own index for the tag
# filter of the offer list and the RESTRICT check.
job_offer_tags: Table = Table(
    "job_offer_tags",
    Base.metadata,
    Column("job_offer_id", ForeignKey("job_offers.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="RESTRICT"), primary_key=True, index=True),
)
