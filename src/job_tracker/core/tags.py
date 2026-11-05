"""Normalising tag names, so one tag has one spelling (D-09, decisions: "Tag").

Tags are free text typed by the client; ``FastAPI``, ``fastapi`` and `` fastapi `` must be
one tag, or filtering offers by tag stops working. The allowed characters are also checked
by the database (``ck_tags_name_format``).
"""

import re

# Must match the length of the tags.name column.
MAX_TAG_LENGTH: int = 50
# The allowed characters as the body of a regular-expression character class; shared with
# the database check ``ck_tags_name_format``, so both enforce the same rule. "-" stays last:
# in the middle of a class it would mean a range.
TAG_NAME_CHARACTERS: str = "a-z0-9.+#-"
# A tag needs at least one of these: a name made only of punctuation ("---") is a typo.
LETTER_OR_DIGIT: str = "[a-z0-9]"
TAG_NAME_PATTERN: re.Pattern[str] = re.compile(f"[{TAG_NAME_CHARACTERS}]+")
LETTER_OR_DIGIT_PATTERN: re.Pattern[str] = re.compile(f"{LETTER_OR_DIGIT}")


def normalise_tag_name(tag_name: str) -> str:
    """Return the canonical form of ``tag_name``, or raise ``ValueError`` if it cannot be a tag.

    The name is trimmed and lower-cased, and every run of whitespace inside it becomes one
    ``-`` (``"Machine  Learning"`` → ``"machine-learning"``). The result must not be empty,
    must have at most ``MAX_TAG_LENGTH`` characters and may contain only ``a-z``, ``0-9``,
    ``.``, ``+``, ``#`` and ``-`` (so ``c++``, ``c#``, ``.net`` and ``node.js`` are valid),
    with at least one letter or digit (``---`` is rejected); other characters are rejected,
    not replaced. Used as a schema validator, the ``ValueError`` becomes a ``422`` whose
    message does not repeat the rejected name.

    Normalising a normalised name returns it unchanged.
    """
    tag_name = tag_name.strip()
    if not tag_name:
        raise ValueError("Tag name must not be empty")
    tag_name = tag_name.lower()
    tag_name = re.sub(r"\s+", "-", tag_name)
    if len(tag_name) > MAX_TAG_LENGTH:
        raise ValueError(f"Tag has to be at most {MAX_TAG_LENGTH} characters long")
    if not TAG_NAME_PATTERN.fullmatch(tag_name):
        raise ValueError("Tag name must contain only a-z, 0-9, '.', '+', '#' and '-'")
    if not LETTER_OR_DIGIT_PATTERN.search(tag_name):
        raise ValueError("Tag name must contain at least one letter or digit")
    return tag_name
