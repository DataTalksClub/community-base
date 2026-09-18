"""Convert one course repository to the content format (`FORMAT.md` 3.8).

    uv run python -m community_base.content_sync.convert.courses <path> [--apply]

Deleted from this package after the last conversion merges, which is `D7.4`
step 9. It exists for one pass over the eight course repositories.

What it converts, in the order the walk visits it:

- `content.yaml` is written, declaring the one `course` collection and the
  `ignore` list that names every directory of the repository that is not
  content. `ignore` moves out of `course.yaml`, which no longer carries it.
- `course.yaml` loses `schema_version`, `published`, `cohorts` and
  `current_cohort`, flattens `urls` into `repository_url`, `docs_url`,
  `faq_url` and `discussion_url`, renames `cover_image` to `image` and
  `default_unit_access` to `default_unit_required_level`, and moves every key
  the format does not name under `extra`.
- `module.yaml` loses `schema_version` and its `units:` list, whose
  `content_id` and `title` are pushed into each unit file's front matter, and
  renames `bonus` to `is_bonus`. The overview stays `README.md`.
- a unit loses `prev_url` and `next_url`, which the format derives from order,
  turns `is_homework` into `kind: homework`, and loses the leading H1 that
  repeats its title, which the renderer strips anyway.
- `cohort.yaml` loses `schema_version`, `identifier`, `course`, `published`
  and `curriculum`, gains the `title` decision D34 makes required, keeps
  `archive` as the mapping decision D38 makes it, and rewrites each homework
  binding's `module` to a module slug and its `source` to a path relative to
  the cohort directory.
- `homework.yaml` loses `schema_version`.

What it refuses, rather than guess:

- a `units:` entry naming a file that is not there, or naming a
  `content_id` or `title` that contradicts one the unit file already carries;
- a `cohorts:` entry in `course.yaml` with no `cohorts/<identifier>/` to match
  it, because the directory is what places a cohort and dropping the list
  would drop the cohort;
- a cohort whose `curriculum` and `archive` disagree;
- a homework binding naming a module the repository does not have;
- a module directory holding both unit files and submodule directories;
- a YAML file it cannot parse.

Every refusal leaves its file exactly as it was found and is printed in the
report with the rule it failed. A key the format cannot express is moved under
`extra` rather than dropped, and the report prints the value of every key that
is dropped outright.
"""

from __future__ import annotations

import argparse
import re
import sys
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from community_base.content_sync.convert.report import (
    ConversionReport,
    dump_yaml,
    inventory,
    ordered,
    read_front_matter,
    write_front_matter,
)
from community_base.content_sync.kinds.base import ORDER_PREFIX_PATTERN
from community_base.content_sync.kinds.layouts import (
    CODE_DIR,
    COHORT_MANIFEST,
    COHORTS_DIR,
    COURSE_MANIFEST,
    HOMEWORK_MANIFEST,
    MODULE_MANIFEST,
    README,
)

__all__ = ["convert_course_repository", "main"]

MANIFEST_NAME = "content.yaml"
ASSET_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf")

#: Core keys first, in the order `FORMAT.md` section 3.3 lists them.
CORE_ORDER = (
    "content_id",
    "title",
    "slug",
    "summary",
    "status",
    "required_level",
    "sort_order",
    "tags",
    "image",
    "date",
)

COURSE_KEYS = (
    "description",
    "instructors",
    "default_unit_required_level",
    "outcome",
    "prerequisites",
    "discussion_url",
    "repository_url",
    "docs_url",
    "faq_url",
    "hashtag",
    "testimonials",
)
MODULE_KEYS = ("is_bonus", "available_after_days")
UNIT_KEYS = ("kind", "video_url", "timestamps", "session_position", "is_bonus", "code")
COHORT_KEYS = (
    "delivery",
    "start_date",
    "end_date",
    "modules",
    "archive",
    "registration_url",
    "hashtag",
    "homework",
)
HOMEWORK_KEYS = ("instructions_path", "due_at", "initial_state", "form", "questions")

#: `urls:` in a schema-2 course manifest, flattened (section 3.8).
URL_KEYS = {
    "repository": "repository_url",
    "docs": "docs_url",
    "faq": "faq_url",
    "discussion": "discussion_url",
}

#: Keys the format replaces outright. The report prints the value of each.
COURSE_DROPPED = ("schema_version", "published", "cohorts", "current_cohort", "ignore", "urls")
MODULE_DROPPED = ("schema_version", "units")
UNIT_DROPPED = ("schema_version", "prev_url", "next_url", "is_homework", "published")
COHORT_DROPPED = (
    "schema_version",
    "identifier",
    "course",
    "published",
    "curriculum",
    "legacy_slug",
    "year",
    "format",
    "flow",
)
HOMEWORK_DROPPED = ("schema_version",)

RENAMED = {
    "cover_image": "image",
    "cover_image_url": "image",
    "default_unit_access": "default_unit_required_level",
    "bonus": "is_bonus",
    "description": "summary",
}

STRIKETHROUGH = re.compile(r"~~([^~\s][^~]*)~~")
STYLE_ATTRIBUTE = re.compile(r'\s+style\s*=\s*(["\'])[^"\']*\1', re.IGNORECASE)
FENCE = re.compile(r"^(\s*)(```+|~~~+)")


class Refused(Exception):
    """One file the conversion will not guess at; it stays as it was."""

    def __init__(self, rule: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule
        self.message = message


# --- the entry point ----------------------------------------------------------


def convert_course_repository(root: Path, *, apply: bool = True) -> ConversionReport:
    """Convert the course repository at `root` in place and report on it.

    `apply=False` runs every rule and writes nothing, which is how a dry run
    produces the same report without touching the checkout.
    """

    root = Path(root)
    report = ConversionReport(repository=root.name, before=inventory(root))
    conversion = _Conversion(root, report, apply=apply)
    conversion.run()
    report.after = inventory(root)
    return report


class _Conversion:
    """One pass over one repository. Nothing is written before the walk ends.

    Every rule appends to `self.writes`, so a refusal found late leaves the
    checkout untouched rather than half converted.
    """

    def __init__(self, root: Path, report: ConversionReport, *, apply: bool) -> None:
        self.root = root
        self.report = report
        self.apply = apply
        self.writes: list[tuple[str, str]] = []
        self.touched: set[str] = set()
        self.ignore: list[str] = []
        self.module_slugs: dict[str, str] = {}

    # -- the walk ------------------------------------------------------------

    def run(self) -> None:
        course = self._load(COURSE_MANIFEST)
        if course is None:
            return
        self._seed_ignore()
        declared = course.get("ignore")
        if isinstance(declared, Sequence) and not isinstance(declared, str):
            # `course.yaml` carried `ignore` and `content.yaml` carries it now.
            # It is harvested before the module walk so that a file it hides is
            # never a unit candidate and never a refusal.
            self.ignore.extend(str(item) for item in declared)
        self._collect_modules()
        self._convert_modules()
        self._convert_cohorts(course)
        self._convert_course(course)
        self._write_manifest()
        self._audit_links()
        self._account()
        self._flush()

    def _account(self) -> None:
        """Every file no rule touched is still a file the report answers for."""

        for path in sorted(self.report.before):
            if path not in self.touched:
                self.report.record(path, "unchanged")

    def _flush(self) -> None:
        if not self.apply:
            return
        for path, text in self.writes:
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")

    def _write(self, path: str, text: str, *, details: Sequence[str] = ()) -> None:
        existing = self.root / path
        if existing.is_file() and existing.read_text(encoding="utf-8") == text:
            self.report.record(path, "unchanged")
            self.touched.add(path)
            return
        action = "rewritten" if existing.is_file() else "created"
        self.writes.append((path, text))
        self.report.record(path, action, details=details)
        self.touched.add(path)

    def _load(self, path: str) -> dict[str, Any] | None:
        target = self.root / path
        if not target.is_file():
            self.report.refuse(path, "3.8", "a course collection needs course.yaml")
            return None
        try:
            data = yaml.safe_load(target.read_text(encoding="utf-8"))
        except yaml.YAMLError as error:
            self.report.refuse(path, "3.2", f"YAML does not parse: {error}")
            return None
        if not isinstance(data, Mapping):
            self.report.refuse(path, "3.2", "a manifest is a mapping")
            return None
        return dict(data)

    def _seed_ignore(self) -> None:
        """Carry an existing `content.yaml` `ignore` list forward.

        This is what makes the conversion idempotent over a decision it took
        once: a markdown file a module manifest did not list was declared
        not-content, and on a second run the `units:` list that said so is
        gone. An entry a person added by hand survives for the same reason.
        """

        manifest = self.root / MANIFEST_NAME
        if not manifest.is_file():
            return
        try:
            data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        except yaml.YAMLError as error:
            self.report.refuse(MANIFEST_NAME, "3.1", f"YAML does not parse: {error}")
            return
        declared = data.get("ignore") if isinstance(data, Mapping) else None
        if isinstance(declared, Sequence) and not isinstance(declared, str):
            self.ignore.extend(str(item) for item in declared)

    def _ignored(self, path: str) -> bool:
        candidate = PurePosixPath(path)
        return any(candidate.full_match(pattern) for pattern in self.ignore)

    # -- modules and units ---------------------------------------------------

    def _collect_modules(self) -> None:
        """Every module directory, and the slug its name strips to."""

        for manifest in sorted(self.root.glob(f"**/{MODULE_MANIFEST}")):
            directory = manifest.parent
            rel = directory.relative_to(self.root).as_posix()
            self.module_slugs[rel] = _slug_of(directory.name)

    def _convert_modules(self) -> None:
        for rel in sorted(self.module_slugs):
            directory = self.root / rel
            path = f"{rel}/{MODULE_MANIFEST}"
            data = self._load(path)
            if data is None:
                continue
            try:
                declared = self._unit_declarations(rel, data)
                self._check_module_shape(rel, directory)
            except Refused as refusal:
                self.report.refuse(path, refusal.rule, refusal.message)
                continue
            self._convert_units(rel, directory, declared, enumerated=data.get("units") is not None)
            self._write(path, dump_yaml(self._module_values(data)), details=_dropped(data, rel))

    def _unit_declarations(self, rel: str, data: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        """The `units:` list as `{unit path: {content_id, title}}`.

        A schema-2 module manifest holds the identity and the title of every
        unit; the format puts both in the unit file. An entry naming a file the
        module directory does not hold is refused: dropping the list would drop
        the identity with it.
        """

        declared = data.get("units")
        if declared is None:
            return {}
        if not isinstance(declared, Sequence) or isinstance(declared, str):
            raise Refused("3.8", "units is a list of {content_id, title, path}")
        found: dict[str, dict[str, Any]] = {}
        for index, entry in enumerate(declared):
            if not isinstance(entry, Mapping) or not entry.get("path"):
                raise Refused("3.8", f"units/{index} carries no path")
            name = str(entry["path"])
            if not (self.root / rel / name).is_file():
                raise Refused("3.8", f"units/{index} names {name}, which is not in {rel}")
            found[name] = {
                key: entry[key] for key in ("content_id", "title", "sort_order") if key in entry
            }
        return found

    def _check_module_shape(self, rel: str, directory: Path) -> None:
        units = [
            item.name
            for item in sorted(directory.iterdir())
            if item.is_file() and item.suffix == ".md" and item.name != README
        ]
        submodules = [
            item.name
            for item in sorted(directory.iterdir())
            if item.is_dir() and (item / MODULE_MANIFEST).is_file()
        ]
        if units and submodules:
            raise Refused(
                "3.5",
                "a module directory holds either submodule directories or unit files, "
                f"found {len(units)} unit file(s) and {len(submodules)} submodule(s)",
            )

    def _convert_units(
        self,
        rel: str,
        directory: Path,
        declared: Mapping[str, Mapping[str, Any]],
        *,
        enumerated: bool,
    ) -> None:
        for item in sorted(directory.iterdir()):
            if not item.is_file() or item.suffix != ".md" or item.name == README:
                continue
            path = f"{rel}/{item.name}"
            if self._ignored(path):
                continue
            if enumerated and item.name not in declared:
                # A schema-2 module manifest enumerates its units, so a markdown
                # file it does not list is not a unit. That is the manifest's
                # statement, not a guess, and the file is declared not-content
                # rather than minted an identity.
                self.ignore.append(path)
                self.report.note(
                    f"{path}: module.yaml does not list it as a unit; declared ignored"
                )
                continue
            text = item.read_text(encoding="utf-8")
            front, body = read_front_matter(text)
            supplied = declared.get(item.name, {})
            try:
                values, details = self._unit_values(front or {}, supplied, path)
            except Refused as refusal:
                self.report.refuse(path, refusal.rule, refusal.message)
                self.report.record(path, "refused")
                self.touched.add(path)
                continue
            body, body_details = _convert_body(body, str(values.get("title") or ""))
            self._write(path, write_front_matter(values, body), details=[*details, *body_details])

    def _unit_values(
        self, front: Mapping[str, Any], supplied: Mapping[str, Any], path: str
    ) -> tuple[dict[str, Any], list[str]]:
        data = dict(front)
        details: list[str] = []
        for key in ("content_id", "title", "sort_order"):
            if key not in supplied:
                continue
            written = data.get(key)
            if written is not None and str(written) != str(supplied[key]):
                raise Refused(
                    "3.4",
                    f"{key} in module.yaml is {supplied[key]!r} and in the unit is {written!r}",
                )
            if written is None:
                data[key] = supplied[key]
                details.append(f"took {key} from module.yaml: {supplied[key]!r}")
        if not data.get("content_id"):
            raise Refused("3.3", "no content_id, and module.yaml declares none for this unit")
        if not data.get("title"):
            raise Refused("3.3", "no title, and module.yaml declares none for this unit")
        if data.pop("is_homework", None):
            data["kind"] = "homework"
            details.append("is_homework -> kind: homework")
        return self._shape(data, UNIT_KEYS, UNIT_DROPPED, details, path)

    def _module_values(self, data: Mapping[str, Any]) -> dict[str, Any]:
        values, _ = self._shape(dict(data), MODULE_KEYS, MODULE_DROPPED, [], "")
        return values

    # -- cohorts -------------------------------------------------------------

    def _convert_cohorts(self, course: Mapping[str, Any]) -> None:
        directory = self.root / COHORTS_DIR
        if not directory.is_dir():
            return
        title = str(course.get("title") or "")
        for child in sorted(directory.iterdir()):
            if not child.is_dir():
                continue
            manifest = child / COHORT_MANIFEST
            rel = f"{COHORTS_DIR}/{child.name}"
            if not manifest.is_file():
                # A directory under `cohorts/` with no manifest places nothing.
                # It is opaque archive (section 3.8) and is named in `ignore`
                # rather than guessed into a cohort.
                self.ignore.append(f"{rel}/**")
                self.report.note(
                    f"{rel}: no cohort.yaml; declared opaque archive in {MANIFEST_NAME}"
                )
                continue
            data = self._load(f"{rel}/{COHORT_MANIFEST}")
            if data is None:
                continue
            try:
                values, details = self._cohort_values(data, child.name, title, rel)
            except Refused as refusal:
                self.report.refuse(f"{rel}/{COHORT_MANIFEST}", refusal.rule, refusal.message)
                self.report.record(f"{rel}/{COHORT_MANIFEST}", "refused")
                self.touched.add(f"{rel}/{COHORT_MANIFEST}")
                continue
            self._write(f"{rel}/{COHORT_MANIFEST}", dump_yaml(values), details=details)
            self._convert_homework(child, rel)

    def _cohort_values(
        self, data: Mapping[str, Any], identifier: str, course_title: str, rel: str
    ) -> tuple[dict[str, Any], list[str]]:
        values = dict(data)
        details: list[str] = []
        written = values.get("identifier")
        if written is not None and str(written) != identifier:
            raise Refused("3.8", f"identifier is {written!r} and the directory is {identifier!r}")
        curriculum = values.get("curriculum")
        archived = values.get("archive") is not None
        if curriculum is not None and (curriculum == "github_archive") != archived:
            raise Refused(
                "3.8",
                f"curriculum is {curriculum!r} and archive is {'set' if archived else 'not set'}",
            )
        if archived and not isinstance(values["archive"], Mapping):
            raise Refused("3.8", "archive is a mapping with an optional notice_path (D38)")
        if not values.get("title"):
            # Decision D34: section 3.3 makes `title` required and the part may
            # not default a core key, so the conversion writes it.
            values["title"] = f"{course_title} {identifier}".strip()
            details.append(f"wrote title (D34): {values['title']!r}")
        values["homework"] = self._bindings(values.get("homework") or (), rel, details)
        if not values["homework"]:
            values.pop("homework")
        return self._shape(values, COHORT_KEYS, COHORT_DROPPED, details, rel)

    def _bindings(self, declared: Any, rel: str, details: list[str]) -> list[dict[str, Any]]:
        if not isinstance(declared, Sequence) or isinstance(declared, str):
            raise Refused("3.8", "homework is a list of {module, source, unit}")
        found: list[dict[str, Any]] = []
        for index, entry in enumerate(declared):
            if not isinstance(entry, Mapping):
                raise Refused("3.8", f"homework/{index} is a mapping")
            binding = dict(entry)
            module = str(binding.get("module") or "")
            slug = _slug_of(module)
            if slug not in set(self.module_slugs.values()):
                raise Refused(
                    "3.8",
                    f"homework/{index} places the module {module!r}, which is not in this course",
                )
            if slug != module:
                details.append(f"homework/{index}/module: {module!r} -> {slug!r}")
            binding["module"] = slug
            source = str(binding.get("source") or "")
            relative = source[len(rel) + 1 :] if source.startswith(f"{rel}/") else source
            if relative != source:
                details.append(f"homework/{index}/source: {source!r} -> {relative!r}")
            binding["source"] = relative
            if not (self.root / rel / relative).is_file():
                raise Refused("3.8", f"homework/{index} names {source!r}, which is not there")
            found.append(binding)
        return found

    def _convert_homework(self, directory: Path, rel: str) -> None:
        for manifest in sorted(directory.glob(f"**/{HOMEWORK_MANIFEST}")):
            path = manifest.relative_to(self.root).as_posix()
            data = self._load(path)
            if data is None:
                continue
            values, details = self._shape(dict(data), HOMEWORK_KEYS, HOMEWORK_DROPPED, [], path)
            self._write(path, dump_yaml(values), details=details)

    # -- the course manifest and content.yaml --------------------------------

    def _convert_course(self, data: Mapping[str, Any]) -> None:
        values = dict(data)
        details: list[str] = []
        urls = values.get("urls")
        if isinstance(urls, Mapping):
            for name, value in urls.items():
                target = URL_KEYS.get(str(name))
                if target is None:
                    raise_refusal = f"urls/{name} has no key in the format"
                    self.report.refuse(COURSE_MANIFEST, "3.8", raise_refusal)
                    continue
                values.setdefault(target, value)
                details.append(f"urls/{name} -> {target}")
        self._check_cohort_list(values, details)
        declared = values.get("ignore")
        if isinstance(declared, Sequence) and not isinstance(declared, str):
            details.append(f"ignore -> {MANIFEST_NAME}: {list(declared)}")
        self._collect_ignores()
        if not str(values.get("description") or "").strip():
            # Section 3.8 requires it and no other key of this manifest carries
            # the same text. Writing one would be the conversion authoring
            # content, which it never does.
            self.report.refuse(
                COURSE_MANIFEST,
                "3.8",
                "required key description is missing and the conversion does not write one",
            )
        converted, more = self._shape(values, COURSE_KEYS, COURSE_DROPPED, details, COURSE_MANIFEST)
        self._write(COURSE_MANIFEST, dump_yaml(converted), details=more)

    def _check_cohort_list(self, values: Mapping[str, Any], details: list[str]) -> None:
        """A `cohorts:` list becomes cohort directories, entry by entry.

        A DataTalks.Club manifest lists cohorts that already have a directory,
        and the list is then the directories restated. An AI Shipping Labs
        manifest lists a cohort that has no directory at all, and the list is
        the only place the cohort is written down, so the entry becomes the
        manifest rather than being dropped. An entry the conversion cannot turn
        into a manifest is refused; nothing about a cohort is invented.
        """

        declared = values.get("cohorts")
        if not isinstance(declared, Sequence) or isinstance(declared, str):
            return
        course_id = str(values.get("content_id") or "")
        title = str(values.get("title") or "")
        for index, entry in enumerate(declared):
            identifier = (
                entry.get("identifier") or entry.get("key") if isinstance(entry, Mapping) else entry
            )
            if identifier is None:
                self.report.refuse(COURSE_MANIFEST, "3.8", f"cohorts/{index} names no cohort")
                continue
            rel = f"{COHORTS_DIR}/{identifier}"
            if (self.root / rel / COHORT_MANIFEST).is_file():
                continue
            written = self._cohort_from_entry(entry, str(identifier), course_id, title, index)
            if written is None:
                continue
            self._write(
                f"{rel}/{COHORT_MANIFEST}",
                dump_yaml(written),
                details=[
                    f"written from cohorts/{index} of {COURSE_MANIFEST}",
                    f"content_id minted from the course content_id and {identifier!r}",
                ],
            )
        details.append(f"cohorts -> the {COHORTS_DIR}/ directories")

    def _cohort_from_entry(
        self, entry: Any, identifier: str, course_id: str, title: str, index: int
    ) -> dict[str, Any] | None:
        """One `cohorts:` entry as a cohort manifest, or None when it is refused."""

        if not isinstance(entry, Mapping):
            self.report.refuse(
                COURSE_MANIFEST,
                "3.8",
                f"cohorts/{index} is {entry!r} and carries nothing a cohort manifest needs",
            )
            return None
        unknown = set(entry) - {"key", "identifier", "name", "start_date", "end_date", "content"}
        if unknown:
            self.report.refuse(
                COURSE_MANIFEST,
                "3.8",
                f"cohorts/{index} carries {sorted(unknown)}, which no cohort key holds",
            )
            return None
        if not course_id:
            self.report.refuse(COURSE_MANIFEST, "3.3", "the course carries no content_id")
            return None
        start, end = entry.get("start_date"), entry.get("end_date")
        if not (start and end):
            self.report.refuse(
                COURSE_MANIFEST,
                "3.8",
                f"cohorts/{index} declares no start_date and end_date, which a published live "
                "cohort needs, and the conversion does not invent a schedule",
            )
            return None
        return {
            # Deterministic, so a second run writes the same identity: the
            # conversion never mints a random one.
            "content_id": str(uuid.uuid5(uuid.UUID(course_id), identifier)),
            "title": str(entry.get("name") or f"{title} {identifier}").strip(),
            "delivery": "live",
            "start_date": str(start),
            "end_date": str(end),
        }

    def _collect_ignores(self) -> None:
        """Name every directory of the repository that is not content.

        A course repository carries notebooks, scripts and datasets beside its
        content. `CourseLayout` ignores a file it does not recognise but not a
        directory, so a directory that is neither a module, a cohort, `code/`
        nor an asset directory is named here. Every markdown file inside one is
        printed in the report, because that is the only content a reader could
        have expected to be synced.
        """

        modules = set(self.module_slugs)
        for child in sorted(self.root.iterdir()):
            if not child.is_dir() or child.name.startswith((".", "_")):
                continue
            rel = child.name
            if rel == COHORTS_DIR or rel in modules or rel == CODE_DIR:
                continue
            if _is_asset_dir(child):
                continue
            self._ignore_directory(child, rel)
        for rel in sorted(modules):
            for child in sorted((self.root / rel).iterdir()):
                if not child.is_dir() or child.name.startswith((".", "_")):
                    continue
                nested = f"{rel}/{child.name}"
                if nested in modules or child.name == CODE_DIR or _is_asset_dir(child):
                    continue
                self._ignore_directory(child, nested)

    def _ignore_directory(self, directory: Path, rel: str) -> None:
        """Declare one directory not-content, without hiding the assets in it.

        A directory that holds assets as well as other files is the common
        case: `NN-module/images/` next to a diagram's `.json` source. Hiding
        the whole directory would make every image in it an unresolved
        reference, so only the files that are not assets are named and the
        directory stays the asset directory section 3.5 skips.
        """

        files = [item for item in directory.glob("**/*") if item.is_file()]
        assets = [item for item in files if item.suffix.lower() in ASSET_SUFFIXES]
        if not assets:
            self.ignore.append(f"{rel}/**")
        else:
            suffixes = sorted(
                {item.suffix for item in files if item.suffix.lower() not in ASSET_SUFFIXES}
            )
            self.ignore.extend(f"{rel}/**/*{suffix}" for suffix in suffixes if suffix)
            self.ignore.extend(
                item.relative_to(self.root).as_posix()
                for item in sorted(files)
                if not item.suffix and item.suffix.lower() not in ASSET_SUFFIXES
            )
        pages = sorted(
            item.relative_to(self.root).as_posix()
            for item in directory.glob("**/*.md")
            if item.name != README
        )
        if pages:
            self.report.note(
                f"{rel}/ is not a module and is declared not-content; "
                f"{len(pages)} markdown file(s) in it stop being candidates: {', '.join(pages[:8])}"
                + (" ..." if len(pages) > 8 else "")
            )

    def _write_manifest(self) -> None:
        manifest = {
            "schema_version": 1,
            "collections": [{"kind": "course", "path": "."}],
        }
        if self.ignore:
            manifest["ignore"] = sorted(dict.fromkeys(self.ignore))
        self._write(MANIFEST_NAME, dump_yaml(manifest))

    # -- what a human still has to look at -----------------------------------

    def _audit_links(self) -> None:
        """Name every relative link of a unit body that resolves to nothing.

        The conversion does not repair a link: a destination that names no
        document, no asset and no repository path is content the author has to
        fix, and guessing which file was meant is exactly the guess this script
        does not make. `check_content` reports the same links as errors; the
        report names them first so the human-review step of `A7.3` and `D7.4`
        has the list before the merge.
        """

        dead: list[str] = []
        for path, text in [*self.writes, *self._unwritten_units()]:
            if not path.endswith(".md"):
                continue
            _, body = read_front_matter(text)
            for line, destination in _relative_links(body):
                target = destination.partition("#")[0].split("?")[0]
                if not target:
                    continue
                resolved = _join(path, target)
                if resolved is None or not (self.root / resolved).exists():
                    dead.append(f"{path}:{line}: {destination}")
        if dead:
            self.report.note(
                f"{len(dead)} relative link(s) resolve to nothing in this repository and need an "
                f"author: {'; '.join(dead)}"
            )

    def _unwritten_units(self) -> list[tuple[str, str]]:
        """Unit files the conversion left alone, so the audit still reads them."""

        written = {path for path, _ in self.writes}
        found: list[tuple[str, str]] = []
        for rel in sorted(self.module_slugs):
            for item in sorted((self.root / rel).iterdir()):
                path = f"{rel}/{item.name}"
                if not item.is_file() or item.suffix != ".md" or item.name == README:
                    continue
                if path in written or self._ignored(path):
                    continue
                found.append((path, item.read_text(encoding="utf-8")))
        return found

    # -- one file's keys -----------------------------------------------------

    def _shape(
        self,
        data: dict[str, Any],
        kind_keys: Sequence[str],
        dropped: Sequence[str],
        details: list[str],
        path: str,
    ) -> tuple[dict[str, Any], list[str]]:
        """One file's keys, in the format's shape, with nothing lost silently.

        A key the format renames is renamed, a key it replaces outright is
        dropped and its value printed, and any other key it does not name is
        moved under `extra`, which section 3.3 keeps for exactly this.
        """

        values = dict(data)
        for old, new in RENAMED.items():
            if old not in values or new in kind_keys and new in values:
                continue
            if old == "description" and "description" in kind_keys:
                continue
            if new in values:
                continue
            values[new] = values.pop(old)
            details.append(f"{old} -> {new}")
        if values.pop("published", None) is False:
            values["status"] = "draft"
            details.append("published: false -> status: draft")
        known = {*CORE_ORDER, *kind_keys, "extra"}
        extra = dict(values.get("extra") or {})
        for name in list(values):
            if name in known:
                continue
            if name in dropped:
                details.append(f"dropped {name}: {values[name]!r}")
                values.pop(name)
                continue
            extra[name] = values.pop(name)
            details.append(f"{name} -> extra")
        if extra:
            values["extra"] = extra
        return ordered(values, (*CORE_ORDER, *kind_keys, "extra")), details


# --- helpers ------------------------------------------------------------------


LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)>\s]+)>?\s*(?:\"[^\"]*\")?\)")


def _relative_links(body: str) -> list[tuple[int, str]]:
    """Every markdown link or image destination that is not external."""

    found: list[tuple[int, str]] = []
    fence: str | None = None
    for number, line in enumerate(body.split("\n"), start=1):
        match = FENCE.match(line)
        if fence is not None:
            if match is not None and match.group(2).startswith(fence):
                fence = None
            continue
        if match is not None:
            fence = match.group(2)
            continue
        for destination in LINK.findall(line):
            if destination.startswith(("http://", "https://", "#", "mailto:", "//", "/")):
                continue
            if ":" in destination.split("/")[0]:
                continue
            found.append((number, destination))
    return found


def _join(source: str, target: str) -> str | None:
    parts = source.split("/")[:-1]
    for part in target.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _slug_of(name: str) -> str:
    return ORDER_PREFIX_PATTERN.sub("", name)


def _is_asset_dir(directory: Path) -> bool:
    files = [item for item in directory.glob("**/*") if item.is_file()]
    return bool(files) and all(item.suffix.lower() in ASSET_SUFFIXES for item in files)


def _dropped(data: Mapping[str, Any], rel: str) -> list[str]:
    units = data.get("units")
    if not units:
        return []
    return [f"units -> the unit files of {rel}/ ({len(units)} of them)"]


def _convert_body(body: str, title: str) -> tuple[str, list[str]]:
    """The two body rewrites section 4.3 names, and the H1 section 3.3 forbids."""

    details: list[str] = []
    body, removed = _strip_leading_h1(body, title)
    if removed:
        details.append("removed the leading H1 that repeats the title")
    lines = body.split("\n")
    fence: str | None = None
    struck = styled = 0
    for index, line in enumerate(lines):
        match = FENCE.match(line)
        if fence is not None:
            if match is not None and match.group(2).startswith(fence):
                fence = None
            continue
        if match is not None:
            fence = match.group(2)
            continue
        rewritten, count = STRIKETHROUGH.subn(r"<del>\1</del>", line)
        struck += count
        rewritten, count = STYLE_ATTRIBUTE.subn("", rewritten)
        styled += count
        lines[index] = rewritten
    if struck:
        details.append(f"~~strikethrough~~ -> <del> ({struck})")
    if styled:
        details.append(f"removed a style attribute the sanitiser drops ({styled})")
    return "\n".join(lines), details


def _strip_leading_h1(body: str, title: str) -> tuple[str, bool]:
    stripped = body.lstrip("\n")
    first, _, rest = stripped.partition("\n")
    if not first.startswith("# "):
        return body, False
    if first[2:].strip().lower() != title.strip().lower():
        return body, False
    return rest.lstrip("\n"), True


# --- the command line ---------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m community_base.content_sync.convert.courses",
        description="Convert a course repository to the content format, in place.",
    )
    parser.add_argument("path", help="the repository to convert")
    parser.add_argument("--dry-run", action="store_true", help="run every rule and write nothing")
    options = parser.parse_args(argv)
    report = convert_course_repository(Path(options.path), apply=not options.dry_run)
    sys.stdout.write(report.render())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
