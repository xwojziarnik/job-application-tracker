"""Normalising tag names before every lookup and insert (D-09).

``FastAPI``, ``fastapi`` and `` fastapi `` must be one tag, or filtering offers by tag stops
working. ``normalise_tag_name`` returns the canonical name and raises ``ValueError`` for a
name that cannot be a tag; a schema using it reports that error as ``422``.
"""

import pytest

from job_tracker.core.tags import MAX_TAG_LENGTH, normalise_tag_name


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("fastapi", "fastapi"),
        ("FastAPI", "fastapi"),
        ("  FastAPI  ", "fastapi"),
        ("Machine Learning", "machine-learning"),
        ("machine    learning", "machine-learning"),
        ("machine\tlearning\nengineer", "machine-learning-engineer"),
        ("CI-CD", "ci-cd"),
        ("Python3", "python3"),
    ],
    ids=[
        "already-normalised",
        "lower-cased",
        "trimmed",
        "space-becomes-hyphen",
        "space-run-becomes-one-hyphen",
        "any-whitespace",
        "hyphen-kept",
        "digits-kept",
    ],
)
def test_name_is_normalised(name: str, expected: str) -> None:
    assert normalise_tag_name(name) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [("C++", "c++"), ("C#", "c#"), (".NET", ".net"), ("Node.js", "node.js")],
)
def test_punctuation_used_in_technology_names_is_allowed(name: str, expected: str) -> None:
    assert normalise_tag_name(name) == expected


@pytest.mark.parametrize(
    "name",
    ["machine_learning", "ci/cd", "python!", "łódź", "naïve", "<script>", "a,b", "tag?"],
)
def test_name_with_a_character_outside_the_allowed_set_is_rejected(name: str) -> None:
    with pytest.raises(ValueError, match="must contain only"):
        normalise_tag_name(name)


@pytest.mark.parametrize("name", ["---", ".", "#", "+", ".-#+", "- -"])
def test_name_without_a_letter_or_digit_is_rejected(name: str) -> None:
    # Only punctuation is a typo, not a technology; "c#" or ".net" still pass.
    with pytest.raises(ValueError, match="at least one letter or digit"):
        normalise_tag_name(name)


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_blank_name_is_rejected(name: str) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        normalise_tag_name(name)


def test_name_at_the_length_limit_is_accepted() -> None:
    name = "a" * MAX_TAG_LENGTH

    assert normalise_tag_name(name) == name


def test_name_longer_than_the_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="at most 50"):
        normalise_tag_name("a" * (MAX_TAG_LENGTH + 1))


def test_length_is_checked_after_trimming() -> None:
    name = "  " + "a" * MAX_TAG_LENGTH + "  "

    assert normalise_tag_name(name) == "a" * MAX_TAG_LENGTH


def test_spellings_of_one_tag_normalise_to_the_same_name() -> None:
    spellings = ["FastAPI", "fastapi", " fastapi ", "FASTAPI", "\tFastApi\n"]

    assert {normalise_tag_name(name) for name in spellings} == {"fastapi"}


@pytest.mark.parametrize("name", ["Machine Learning", "  C++ ", "node.js", "CI-CD"])
def test_normalising_twice_gives_the_same_result(name: str) -> None:
    once = normalise_tag_name(name)

    assert normalise_tag_name(once) == once


def test_maximum_length_is_fifty() -> None:
    # Must match the length of the tags.name column (decisions: "Tag").
    assert MAX_TAG_LENGTH == 50
