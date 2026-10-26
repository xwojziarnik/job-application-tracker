"""Release helper used by CI on the main branch.

Commands:
  bump     Read commit subjects from stdin and print the hatch version segment to bump
           (major, minor or fix), or nothing when no commit asks for a release.
  check    Validate the structure of CHANGELOG.md.
  release  Move the Unreleased entries of CHANGELOG.md into a new version section and
           regenerate the comparison links at the end of the file.

A commit asks for a release when its subject ends with [major], [minor] or [fix].
"""

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

BUMP_ORDER = ("fix", "minor", "major")
BUMP_MARKER = re.compile(r"\[(major|minor|fix)\]\s*$")

CHANGE_TYPES = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")
UNRELEASED = "Unreleased"

SECTION_HEADING = re.compile(r"^## \[(?P<name>[^\]]+)\](?: - \d{4}-\d{2}-\d{2})?\s*$")
SUBSECTION_HEADING = re.compile(r"^### (?P<name>.+?)\s*$")
LINK_DEFINITION = re.compile(r"^\[[^\]]+\]: \S+\s*$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")


class ChangelogError(Exception):
    pass


@dataclass
class Section:
    name: str
    heading: str
    body: list[str] = field(default_factory=list)


@dataclass
class Changelog:
    preamble: list[str]
    sections: list[Section]

    @property
    def unreleased(self) -> Section:
        for section in self.sections:
            if section.name == UNRELEASED:
                return section
        raise ChangelogError(f"CHANGELOG.md has no '## [{UNRELEASED}]' section")

    @property
    def versions(self) -> list[str]:
        """Released versions, newest first."""
        return [s.name for s in self.sections if s.name != UNRELEASED]


def detect_bump(commit_subjects: list[str]) -> str | None:
    """Return the highest bump requested by the commit subjects, if any."""
    requested = {m.group(1) for s in commit_subjects if (m := BUMP_MARKER.search(s))}
    for bump in reversed(BUMP_ORDER):
        if bump in requested:
            return bump
    return None


def parse_changelog(text: str) -> Changelog:
    lines = text.splitlines()
    # Link definitions at the end are always regenerated, so drop them here.
    while lines and (not lines[-1].strip() or LINK_DEFINITION.match(lines[-1])):
        lines.pop()

    preamble: list[str] = []
    sections: list[Section] = []
    for line in lines:
        if match := SECTION_HEADING.match(line):
            sections.append(Section(name=match.group("name"), heading=line))
        elif sections:
            sections[-1].body.append(line)
        else:
            preamble.append(line)

    changelog = Changelog(preamble=preamble, sections=sections)
    for name in changelog.versions:
        if not VERSION.match(name):
            raise ChangelogError(f"Invalid version heading: [{name}]")
    parse_entries(changelog.unreleased)
    return changelog


def parse_entries(section: Section) -> dict[str, list[str]]:
    """Map each change type to its non-blank lines, validating subsection names."""
    entries: dict[str, list[str]] = {}
    current: str | None = None
    for line in section.body:
        if match := SUBSECTION_HEADING.match(line):
            current = match.group("name")
            if current not in CHANGE_TYPES:
                raise ChangelogError(
                    f"Unknown subsection '### {current}', expected one of: "
                    + ", ".join(CHANGE_TYPES)
                )
            entries.setdefault(current, [])
        elif line.strip():
            if current is None:
                raise ChangelogError(f"Entry outside a subsection in [{section.name}]: {line}")
            entries[current].append(line)
    return {name: lines for name, lines in entries.items() if lines}


def render_subsections(entries: dict[str, list[str]]) -> list[str]:
    lines: list[str] = []
    for name in CHANGE_TYPES:
        if name in entries:
            lines += [f"### {name}", "", *entries[name], ""]
    return lines


def empty_unreleased_template() -> list[str]:
    lines: list[str] = []
    for name in CHANGE_TYPES:
        lines += [f"### {name}", ""]
    return lines


def render_links(versions: list[str], repo_url: str) -> list[str]:
    unreleased_target = (
        f"{repo_url}/compare/v{versions[0]}...HEAD" if versions else f"{repo_url}/commits/HEAD"
    )
    links = [f"[{UNRELEASED}]: {unreleased_target}"]
    for newer, older in zip(versions, [*versions[1:], None], strict=True):
        if older is None:
            links.append(f"[{newer}]: {repo_url}/releases/tag/v{newer}")
        else:
            links.append(f"[{newer}]: {repo_url}/compare/v{older}...v{newer}")
    return links


def release(text: str, version: str, date: str, repo_url: str) -> str:
    if not VERSION.match(version):
        raise ChangelogError(f"Invalid version: {version}")

    changelog = parse_changelog(text)
    if version in changelog.versions:
        raise ChangelogError(f"Version {version} is already in CHANGELOG.md")

    entries = parse_entries(changelog.unreleased)
    if not entries:
        raise ChangelogError(
            f"The [{UNRELEASED}] section is empty; describe the changes before releasing"
        )

    new_section = Section(
        name=version,
        heading=f"## [{version}] - {date}",
        body=["", *render_subsections(entries)],
    )
    changelog.unreleased.body = ["", *empty_unreleased_template()]
    index = changelog.sections.index(changelog.unreleased)
    changelog.sections.insert(index + 1, new_section)

    lines = list(changelog.preamble)
    for section in changelog.sections:
        lines += [section.heading, *section.body]
    while lines and not lines[-1].strip():
        lines.pop()
    lines += ["", *render_links(changelog.versions, repo_url.rstrip("/"))]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("bump", help="print the bump requested by commit subjects on stdin")

    check = commands.add_parser("check", help="validate CHANGELOG.md")
    check.add_argument("--file", type=Path, default=Path("CHANGELOG.md"))

    rel = commands.add_parser("release", help="turn Unreleased into a version section")
    rel.add_argument("version")
    rel.add_argument("--date", required=True, help="release date, YYYY-MM-DD")
    rel.add_argument("--repo-url", required=True, help="e.g. https://github.com/owner/repo")
    rel.add_argument("--file", type=Path, default=Path("CHANGELOG.md"))

    args = parser.parse_args(argv)
    try:
        if args.command == "bump":
            print(detect_bump(sys.stdin.read().splitlines()) or "")
        elif args.command == "check":
            parse_changelog(args.file.read_text(encoding="utf-8"))
        else:
            text = args.file.read_text(encoding="utf-8")
            updated = release(text, args.version, args.date, args.repo_url)
            args.file.write_text(updated, encoding="utf-8")
    except ChangelogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
