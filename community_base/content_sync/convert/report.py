"""What a conversion changed, and the proof that it lost nothing.

A conversion script rewrites every file of a repository, so the only usable
evidence is an inventory rather than a diff read by eye. This module takes one
before the conversion and one after it, and :meth:`ConversionReport.verify`
refuses to call the run a success unless the two account for each other file by
file: every path that existed is unchanged, rewritten, renamed, removed by a
named rule or refused, and every path that exists now was there before or was
created by a named rule.

Key-level accounting is the second half. A rewritten manifest or front matter
records one line per key it stopped writing, with the value that key held, so a
reviewer reads what the conversion decided rather than trusting that it decided
well. A key the format cannot express is moved under `extra` rather than
dropped; only a key the format replaces outright is dropped, and then its old
value is printed.

Nothing here knows about courses or documents. Both scripts build the same
report and the site issues read the same format.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "ACTIONS",
    "ConversionReport",
    "FileChange",
    "Refusal",
    "dump_yaml",
    "inventory",
    "ordered",
    "read_front_matter",
    "write_front_matter",
]

#: What a conversion may do to one file. Anything else is a bug in a script.
ACTIONS = ("unchanged", "rewritten", "renamed", "created", "removed", "refused")

FENCE = "---"


@dataclass(frozen=True, slots=True)
class FileChange:
    """One file the conversion touched, and what it did to it."""

    path: str
    action: str
    target: str = ""
    details: tuple[str, ...] = ()

    def render(self) -> str:
        where = f"{self.path} -> {self.target}" if self.target else self.path
        head = f"  {self.action:<10} {where}"
        return "\n".join([head, *(f"               {line}" for line in self.details)])


@dataclass(frozen=True, slots=True)
class Refusal:
    """One construct the conversion did not understand and did not guess at."""

    path: str
    rule: str
    message: str

    def render(self) -> str:
        return f"  {self.path}: [{self.rule}] {self.message}"


@dataclass
class ConversionReport:
    """The before and after inventory of one converted repository."""

    repository: str
    before: dict[str, str] = field(default_factory=dict)
    after: dict[str, str] = field(default_factory=dict)
    changes: list[FileChange] = field(default_factory=list)
    refusals: list[Refusal] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    # -- recording -----------------------------------------------------------

    def record(self, path: str, action: str, *, target: str = "", details: Iterable[str] = ()):
        if action not in ACTIONS:
            raise ValueError(f"unknown conversion action: {action}")
        self.changes.append(FileChange(path, action, target, tuple(details)))

    def refuse(self, path: str, rule: str, message: str) -> None:
        self.refusals.append(Refusal(path, rule, message))

    def note(self, message: str) -> None:
        self.notes.append(message)

    # -- counting ------------------------------------------------------------

    def counted(self, action: str) -> int:
        return sum(1 for change in self.changes if change.action == action)

    @property
    def converted(self) -> int:
        """Files the conversion wrote: rewritten, renamed or created."""

        return sum(self.counted(action) for action in ("rewritten", "renamed", "created"))

    @property
    def ok(self) -> bool:
        return not self.refusals and not self.verify()

    # -- the proof -----------------------------------------------------------

    def verify(self) -> list[str]:
        """Every way the two inventories fail to account for each other.

        An empty list is the claim the conversion makes: no file vanished
        without a rule naming it, and no file appeared without one either.
        """

        problems: list[str] = []
        moved = {change.path: change for change in self.changes}
        landed: dict[str, FileChange] = {}
        for change in self.changes:
            key = change.target or change.path
            if change.action == "removed":
                continue
            if key in landed:
                problems.append(f"{key}: written by two rules")
            landed[key] = change
        for path in sorted(self.before):
            change = moved.get(path)
            if change is None:
                problems.append(
                    f"{path}: existed before the conversion and no rule accounts for it"
                )
            elif change.action in ("unchanged", "refused") and path not in self.after:
                problems.append(f"{path}: reported {change.action} but is gone")
            elif change.action == "renamed" and change.target not in self.after:
                problems.append(f"{path}: renamed to {change.target}, which is not there")
        for path in sorted(self.after):
            if path in self.before:
                continue
            if path not in landed:
                problems.append(f"{path}: appeared and no rule accounts for it")
        for change in self.changes:
            if change.action == "unchanged" and self.before.get(change.path) != self.after.get(
                change.path
            ):
                problems.append(f"{change.path}: reported unchanged but its bytes differ")
        return problems

    # -- rendering -----------------------------------------------------------

    def render(self) -> str:
        lines = [
            f"# conversion report: {self.repository}",
            "",
            f"files before: {len(self.before)}",
            f"files after:  {len(self.after)}",
            "",
            "| action | files |",
            "|---|---|",
        ]
        lines.extend(f"| {action} | {self.counted(action)} |" for action in ACTIONS)
        lines.append("")
        if self.notes:
            lines.append("## notes")
            lines.extend(f"  {note}" for note in self.notes)
            lines.append("")
        lines.append("## refusals")
        if self.refusals:
            lines.extend(item.render() for item in self.refusals)
        else:
            lines.append("  none")
        lines.append("")
        lines.append("## changes")
        lines.extend(change.render() for change in self.changes if change.action != "unchanged")
        lines.append("")
        problems = self.verify()
        lines.append("## inventory")
        if problems:
            lines.extend(f"  UNACCOUNTED {problem}" for problem in problems)
        else:
            lines.append("  every file before the conversion is accounted for after it")
        return "\n".join(lines) + "\n"


# --- the inventory ------------------------------------------------------------


def inventory(root: Path) -> dict[str, str]:
    """Every tracked file of a checkout, by repository path, as a digest.

    Hidden directories are skipped because a conversion never writes into one
    and `.git` would swamp the count. Everything else is counted, including the
    files the conversion is about to declare not-content: a file declared
    `ignore` is still a file that must still be there afterwards.
    """

    found: dict[str, str] = {}
    for path in sorted(_walk(root)):
        rel = path.relative_to(root).as_posix()
        found[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


def _walk(root: Path) -> Iterator[Path]:
    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        if entry.name == ".git" or entry.is_symlink():
            continue
        if entry.is_dir():
            yield from _walk(entry)
        elif entry.is_file():
            yield entry


# --- reading and writing the two file shapes ----------------------------------


def read_front_matter(text: str) -> tuple[dict[str, Any] | None, str]:
    """A markdown file as `(front matter, body)`; `None` when it carries none.

    The body is returned exactly as it was written, including its leading
    newlines, so a conversion that only changes keys leaves the prose alone.
    """

    if not text.startswith(FENCE):
        return None, text
    rest = text[len(FENCE) :]
    if rest[:1] not in ("\n", "\r"):
        return None, text
    end = rest.find(f"\n{FENCE}")
    if end < 0:
        return None, text
    block = rest[:end]
    after = rest[end + 1 + len(FENCE) :]
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError:
        return None, text
    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        return None, text
    return dict(data), after.lstrip("\r\n")


def write_front_matter(data: Mapping[str, Any], body: str) -> str:
    """One markdown file: the front matter, then the body as it was."""

    return f"{FENCE}\n{dump_yaml(data)}{FENCE}\n\n{body.lstrip(chr(10))}"


class _Dumper(yaml.SafeDumper):
    """The one dumper a conversion writes with.

    Multi-line strings come out as literal blocks, because a course
    description folded into quoted YAML is unreadable and a reviewer has to
    read every converted file. Everything else is `safe_dump`.
    """


def _literal_string(dumper: yaml.SafeDumper, value: str):
    style = "|" if "\n" in value.rstrip("\n") else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _literal_string)


def dump_yaml(data: Mapping[str, Any]) -> str:
    """One mapping as the YAML a conversion writes.

    Key order is the caller's, never alphabetical: the format lists core keys
    first and a reader of a converted file should find them there. The dump is
    deterministic, which is what makes a second run produce no diff.
    """

    return yaml.dump(
        dict(data),
        Dumper=_Dumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100,
    )


def ordered(data: Mapping[str, Any], order: Iterable[str]) -> dict[str, Any]:
    """`data` with the named keys first, in that order, then the rest as given."""

    names = list(order)
    first = {name: data[name] for name in names if name in data}
    rest = {name: value for name, value in data.items() if name not in first}
    return {**first, **rest}
