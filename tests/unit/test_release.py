from pathlib import Path

import pytest
from release import ChangelogError, detect_bump, main, parse_changelog, release

REPO = "https://github.com/owner/repo"

FIRST_RELEASE = """\
# Changelog

Intro text.

## [Unreleased]

### Added

- New endpoint.

### Changed

### Fixed

- A bug.

[Unreleased]: https://github.com/owner/repo/commits/HEAD
"""

EMPTY_TEMPLATE = """\
## [Unreleased]

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security
"""


@pytest.mark.parametrize(
    ("subjects", "expected"),
    [
        (["feat: add offers [fix]"], "fix"),
        (["feat: add offers [minor]"], "minor"),
        (["refactor: drop v1 [major]"], "major"),
        (["a [fix]", "b [major]", "c [minor]"], "major"),
        (["a [fix]", "b [minor]"], "minor"),
        (["docs: update readme"], None),
        (["[fix] marker at the start does not count"], None),
        (["chore(release): v1.0.0 [skip ci]"], None),
        ([], None),
    ],
)
def test_detect_bump(subjects: list[str], expected: str | None) -> None:
    assert detect_bump(subjects) == expected


def test_first_release_moves_entries_and_links_to_tag() -> None:
    result = release(FIRST_RELEASE, "0.1.0", "2026-10-26", REPO)

    assert result == (
        "# Changelog\n\nIntro text.\n\n" + EMPTY_TEMPLATE + "\n## [0.1.0] - 2026-10-26\n\n"
        "### Added\n\n- New endpoint.\n\n"
        "### Fixed\n\n- A bug.\n\n"
        "[Unreleased]: https://github.com/owner/repo/compare/v0.1.0...HEAD\n"
        "[0.1.0]: https://github.com/owner/repo/releases/tag/v0.1.0\n"
    )


def test_next_release_links_compare_consecutive_versions() -> None:
    first = release(FIRST_RELEASE, "0.1.0", "2026-10-26", REPO)
    with_entry = first.replace("### Security\n", "### Security\n\n- Patched a CVE.\n", 1)

    result = release(with_entry, "0.1.1", "2026-11-02", REPO)

    assert "## [0.1.1] - 2026-11-02\n\n### Security\n\n- Patched a CVE.\n" in result
    assert result.index("## [0.1.1]") < result.index("## [0.1.0]")
    assert result.endswith(
        "[Unreleased]: https://github.com/owner/repo/compare/v0.1.1...HEAD\n"
        "[0.1.1]: https://github.com/owner/repo/compare/v0.1.0...v0.1.1\n"
        "[0.1.0]: https://github.com/owner/repo/releases/tag/v0.1.0\n"
    )


def test_release_with_empty_unreleased_is_rejected() -> None:
    text = "# Changelog\n\n" + EMPTY_TEMPLATE

    with pytest.raises(ChangelogError, match="section is empty"):
        release(text, "0.1.0", "2026-10-26", REPO)


def test_release_of_existing_version_is_rejected() -> None:
    first = release(FIRST_RELEASE, "0.1.0", "2026-10-26", REPO)

    with pytest.raises(ChangelogError, match=r"already in CHANGELOG\.md"):
        release(first.replace("### Added\n", "### Added\n\n- More.\n", 1), "0.1.0", "x", REPO)


@pytest.mark.parametrize("version", ["1.0", "v1.0.0", "1.0.0; rm -rf /"])
def test_release_with_invalid_version_is_rejected(version: str) -> None:
    with pytest.raises(ChangelogError, match="Invalid version"):
        release(FIRST_RELEASE, version, "2026-10-26", REPO)


def test_unknown_subsection_is_rejected() -> None:
    text = "# Changelog\n\n## [Unreleased]\n\n### Improvements\n\n- Something.\n"

    with pytest.raises(ChangelogError, match="Unknown subsection '### Improvements'"):
        parse_changelog(text)


def test_entry_outside_subsection_is_rejected() -> None:
    text = "# Changelog\n\n## [Unreleased]\n\n- Loose entry.\n"

    with pytest.raises(ChangelogError, match="Entry outside a subsection"):
        parse_changelog(text)


def test_missing_unreleased_section_is_rejected() -> None:
    with pytest.raises(ChangelogError, match="has no '## \\[Unreleased\\]' section"):
        parse_changelog("# Changelog\n")


def test_project_changelog_is_valid() -> None:
    changelog = Path(__file__).resolve().parents[2] / "CHANGELOG.md"

    assert main(["check", "--file", str(changelog)]) == 0
