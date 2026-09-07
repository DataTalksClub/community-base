"""Parser for the DTC course repository contract (curriculum scope).

Repository layout (version one):

- ``course.yaml`` - course manifest (required for the layout to apply)
- ``SITE.md`` - the repository's website description
- ``module.yaml`` - shared module manifests (``<module>/module.yaml``) or
  cohort-local ones (``cohorts/<identifier>/<module>/module.yaml``)
- ``cohorts/<identifier>/cohort.yaml`` - cohort manifests
- ``cohorts/<identifier>/homework.yaml`` - coursework manifests; left unread
  until the coursework app imports them (C5.2)

Unit markdown carries a strict frontmatter block (``video_url``, ``code``).
Flow entries place modules and projects inside a ``modules``-format cohort;
homework references are validated for shape but not resolved here.
"""

from __future__ import annotations

import re
from dataclasses import fields
from datetime import date
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import yaml

from community_base.curriculum.source import (
    FORMAT_LEGACY,
    FORMAT_MODULES,
    CohortGraph,
    CourseGraph,
    CurriculumParseError,
    ModuleGraph,
    ParsedCurriculum,
    UnitGraph,
)

PARSER_VERSION = "dtc-course-repository-1"
SCHEMA_VERSION = 1

_SITE_DESCRIPTION_PATH = "SITE.md"
_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_SHA1_RE = re.compile(r"[0-9a-f]{40}")
_MAX_TEXT = 20_000
_VIDEO_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


def looks_like_course_repository(checkout) -> bool:
    """True when the checkout root carries a ``course.yaml`` manifest."""

    return any(path.parts == ("course.yaml",) for path in checkout.files())


def parse_dtc_course_repository(checkout) -> ParsedCurriculum:
    """Parse a version-one course repository into the shared graph."""

    if not looks_like_course_repository(checkout):
        raise CurriculumParseError("course.yaml missing at repository root")
    _validate_manifest_placement(checkout)
    content_ids: set[str] = set()

    course = _parse_course(checkout, content_ids)
    modules = {
        path: _parse_module(checkout, path, content_ids)
        for path in _module_manifest_paths(checkout)
    }
    cohorts = _parse_cohorts(checkout, course, modules, content_ids)

    return ParsedCurriculum(
        parser_version=PARSER_VERSION,
        schema_version=SCHEMA_VERSION,
        commit_sha=_commit(checkout),
        course=CourseGraph(
            **{**course, "cohorts": tuple(cohorts)},
        ),
    )


def _commit(checkout):
    candidate = getattr(checkout, "commit_sha", "") or ""
    return candidate if _SHA1_RE.fullmatch(candidate) else None


def _validate_manifest_placement(checkout) -> None:
    for path in checkout.files():
        parts = path.parts
        name = parts[-1]
        if name == "course.yaml":
            valid = len(parts) == 1
        elif name == "module.yaml":
            valid = (len(parts) == 2 and parts[0] != "cohorts") or (
                len(parts) == 4 and parts[0] == "cohorts"
            )
        elif name == "cohort.yaml":
            valid = len(parts) == 3 and parts[0] == "cohorts"
        elif name == "homework.yaml":
            valid = len(parts) == 4 and parts[0] == "cohorts"
        else:
            valid = True
        if not valid:
            raise CurriculumParseError(f"{path}: manifest in unexpected location")


def _module_manifest_paths(checkout) -> list[str]:
    paths = []
    for path in checkout.files():
        if path.name != "module.yaml":
            continue
        parts = path.parts
        if (len(parts) == 2 and parts[0] != "cohorts") or (
            len(parts) == 4 and parts[0] == "cohorts"
        ):
            paths.append(path.as_posix())
    return sorted(paths)


def _parse_course(checkout, content_ids: set[str]) -> dict:
    path = "course.yaml"
    mapping = _mapping(checkout, path)
    _strict(mapping, path, allowed=_COURSE_KEYS, required=_COURSE_KEYS - {"description_path"})
    _schema_version(mapping, path)
    content_id = _content_id(mapping, path, content_ids)
    if mapping.get("description_path") not in (None, _SITE_DESCRIPTION_PATH):
        raise CurriculumParseError(f"{path}:/description_path: only SITE.md is allowed")
    hashtag = _text(mapping["hashtag"], path, "/hashtag", 100)
    if hashtag.startswith("#") or not re.fullmatch(r"[A-Za-z0-9_]*", hashtag):
        raise CurriculumParseError(f"{path}:/hashtag: invalid hashtag")
    description, _source = _site_description(checkout)
    return {
        "content_id": content_id,
        "slug": _slug(mapping["slug"], path, "/slug"),
        "title": _text(mapping["title"], path, "/title", 300),
        "source_path": path,
        "description": description or "",
        "github_repo_url": _https_url(mapping["repository_url"], path, "/repository_url"),
        "docs_url": _https_url(mapping["docs_url"], path, "/docs_url"),
        "faq_url": _https_url(mapping["faq_url"], path, "/faq_url"),
        "hashtag": hashtag,
        "visible": bool(mapping["published"]),
    }


_COURSE_KEYS = frozenset(
    {
        "schema_version",
        "content_id",
        "slug",
        "title",
        "description_path",
        "outcome",
        "repository_url",
        "docs_url",
        "faq_url",
        "hashtag",
        "published",
    }
)


def _site_description(checkout) -> tuple[str | None, str | None]:
    if not any(path.parts == (_SITE_DESCRIPTION_PATH,) for path in checkout.files()):
        return None, None
    description = checkout.read_text(_SITE_DESCRIPTION_PATH).strip()
    if not description:
        raise CurriculumParseError(f"{_SITE_DESCRIPTION_PATH}: description is empty")
    if len(description) > _MAX_TEXT:
        raise CurriculumParseError(f"{_SITE_DESCRIPTION_PATH}: description is too long")
    return description, _SITE_DESCRIPTION_PATH


def _parse_module(checkout, path: str, content_ids: set[str]) -> ModuleGraph:
    mapping = _mapping(checkout, path)
    _strict(
        mapping,
        path,
        allowed=frozenset({"schema_version", "content_id", "slug", "title", "units"}),
        required=frozenset({"schema_version", "content_id", "title", "units"}),
    )
    _schema_version(mapping, path)
    content_id = _content_id(mapping, path, content_ids)
    directory = PurePosixPath(path).parent.name
    module_slug = _slug(directory, path, "/slug")
    if "slug" in mapping and _slug(mapping["slug"], path, "/slug") != module_slug:
        raise CurriculumParseError(f"{path}:/slug: does not match the directory name")

    units = []
    seen_slugs: set[str] = set()
    for index, raw_unit in enumerate(_sequence(mapping["units"], path, "/units", minimum=1)):
        pointer = f"/units/{index}"
        if not isinstance(raw_unit, dict):
            raise CurriculumParseError(f"{path}:{pointer}: unit must be a mapping")
        if "content_id" not in raw_unit or "title" not in raw_unit or "path" not in raw_unit:
            raise CurriculumParseError(f"{path}:{pointer}: unit needs content_id, title, path")
        unexpected = set(raw_unit) - {"content_id", "slug", "title", "path"}
        if unexpected:
            raise CurriculumParseError(f"{path}:{pointer}: unknown keys {sorted(unexpected)}")
        unit_id = str(raw_unit["content_id"])
        _register(unit_id, path, content_ids)
        source_path = _unit_source_path(checkout, path, pointer, str(raw_unit["path"]))
        unit_slug = _slug(PurePosixPath(source_path).stem, path, f"{pointer}/slug")
        if "slug" in raw_unit and _slug(raw_unit["slug"], path, f"{pointer}/slug") != unit_slug:
            raise CurriculumParseError(f"{path}:{pointer}/slug: does not match the file name")
        if unit_slug in seen_slugs:
            raise CurriculumParseError(f"{path}:{pointer}: duplicate unit slug")
        seen_slugs.add(unit_slug)
        raw_markdown = checkout.read_text(source_path)
        body, video_url = _lesson_frontmatter(source_path, raw_markdown)
        units.append(
            UnitGraph(
                content_id=unit_id,
                slug=unit_slug,
                title=_text(raw_unit["title"], path, f"{pointer}/title", 300),
                source_path=source_path,
                body=body,
                video_url=video_url or "",
                sort_order=index,
            )
        )
    return ModuleGraph(
        content_id=content_id,
        slug=module_slug,
        title=_text(mapping["title"], path, "/title", 300),
        source_path=path,
        sort_order=0,
        units=tuple(units),
    )


def _unit_source_path(checkout, path: str, pointer: str, raw: str) -> str:
    """Resolve a manifest-relative unit path, as the donor contract does."""

    base = PurePosixPath(path).parent
    if not isinstance(raw, str) or not raw:
        raise CurriculumParseError(f"{path}:{pointer}/path: expected a path string")
    parts: list[str] = list(base.parts)
    for part in PurePosixPath(raw).parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part not in (".", ""):
            parts.append(part)
    resolved = PurePosixPath(*parts).as_posix()
    if not resolved.endswith(".md"):
        raise CurriculumParseError(f"{path}:{pointer}/path: unit source must be markdown")
    if not any(p.as_posix() == resolved for p in checkout.files()):
        raise CurriculumParseError(f"{path}:{pointer}/path: unit source {resolved} is missing")
    return resolved


def _lesson_frontmatter(path: str, raw: str) -> tuple[str, str | None]:
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return raw, None
    closing = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            closing = index
            break
    if closing is None:
        raise CurriculumParseError(f"{path}: frontmatter is not closed")
    try:
        mapping = yaml.safe_load("".join(lines[1:closing])) or {}
    except yaml.YAMLError as error:
        raise CurriculumParseError(f"{path}: invalid frontmatter: {error}") from None
    if not isinstance(mapping, dict):
        raise CurriculumParseError(f"{path}: frontmatter must be a mapping")
    unexpected = set(mapping) - {"video_url", "code"}
    if unexpected:
        raise CurriculumParseError(f"{path}: unknown frontmatter keys {sorted(unexpected)}")
    video_url = None
    if "video_url" in mapping:
        video_url = _https_url(mapping["video_url"], path, "/frontmatter/video_url")
        hostname = (urlsplit(video_url).hostname or "").casefold()
        if hostname not in _VIDEO_HOSTS:
            raise CurriculumParseError(f"{path}:/frontmatter/video_url: host not allowed")
    return "".join(lines[closing + 1 :]).lstrip("\n"), video_url


def _parse_cohorts(checkout, course: dict, modules: dict[str, ModuleGraph], content_ids):
    explicit = []
    identifiers = []
    for path in checkout.files():
        parts = path.parts
        if len(parts) == 3 and parts[0] == "cohorts" and parts[2] == "cohort.yaml":
            explicit.append(path.as_posix())
        elif len(parts) >= 3 and parts[0] == "cohorts" and parts[1] not in identifiers:
            identifiers.append(parts[1])
    explicit_identifiers = set()
    cohorts = []
    for path in sorted(explicit):
        identifier = PurePosixPath(path).parts[1]
        explicit_identifiers.add(identifier)
        cohorts.append(_parse_cohort(checkout, path, identifier, course, modules, content_ids))
    for identifier in sorted(set(identifiers) - explicit_identifiers):
        cohorts.append(
            CohortGraph(
                content_id=None,
                slug=_slug(identifier, "cohorts", "/identifier"),
                title=identifier,
                curriculum_format=FORMAT_LEGACY,
                source_path=None,
            )
        )
    cohorts.sort(key=lambda cohort: cohort.slug)
    return cohorts


def _parse_cohort(checkout, path, identifier, course, modules, content_ids) -> CohortGraph:
    mapping = _mapping(checkout, path)
    required = frozenset(
        {
            "schema_version",
            "content_id",
            "course",
            "identifier",
            "title",
            "format",
            "published",
        }
    )
    allowed = required | {
        "legacy_slug",
        "year",
        "description",
        "start_date",
        "end_date",
        "flow",
    }
    _strict(mapping, path, allowed=allowed, required=required)
    _schema_version(mapping, path)
    content_id = _content_id(mapping, path, content_ids)
    folder = PurePosixPath(path).parts[1]
    if _slug(mapping["identifier"], path, "/identifier") != folder:
        raise CurriculumParseError(f"{path}:/identifier: does not match the directory name")
    if _slug(mapping["course"], path, "/course") != course["slug"]:
        raise CurriculumParseError(f"{path}:/course: does not match the course slug")
    cohort_format = mapping["format"]
    if cohort_format not in {FORMAT_LEGACY, FORMAT_MODULES}:
        raise CurriculumParseError(f"{path}:/format: unknown cohort format")
    if cohort_format == FORMAT_LEGACY and "flow" in mapping:
        raise CurriculumParseError(f"{path}:/flow: legacy cohorts cannot declare a flow")

    cohort_modules = []
    if cohort_format == FORMAT_MODULES:
        flow = mapping.get("flow")
        if not isinstance(flow, list) or not flow:
            raise CurriculumParseError(f"{path}:/flow: modules cohorts need a flow")
        for index, item in enumerate(flow):
            pointer = f"/flow/{index}"
            if not isinstance(item, dict) or len(item) != 1:
                raise CurriculumParseError(f"{path}:{pointer}: flow item needs exactly one key")
            if "module" in item:
                module_graph = _flow_module(checkout, path, pointer, item["module"], modules)
                module_graph = ModuleGraph(
                    **{
                        **_asdict(module_graph),
                        "sort_order": index,
                    }
                )
                cohort_modules.append(module_graph)
            elif "project" in item:
                continue
            else:
                raise CurriculumParseError(f"{path}:{pointer}: flow item must be module or project")

    return CohortGraph(
        content_id=content_id,
        slug=folder,
        title=_text(mapping["title"], path, "/title", 300),
        curriculum_format=cohort_format,
        start_date=_optional_date(mapping.get("start_date"), path, "/start_date"),
        end_date=_optional_date(mapping.get("end_date"), path, "/end_date"),
        visible=bool(mapping["published"]),
        source_path=path,
        modules=tuple(cohort_modules),
    )


def _flow_module(checkout, path, pointer, raw, modules) -> ModuleGraph:
    if not isinstance(raw, dict):
        raise CurriculumParseError(f"{path}:{pointer}: module reference must be a mapping")
    unexpected = set(raw) - {"source", "homework"}
    if unexpected or "source" not in raw:
        raise CurriculumParseError(
            f"{path}:{pointer}: module reference needs source (and homework)"
        )
    if "homework" not in raw:
        raise CurriculumParseError(
            f"{path}:{pointer}: homework reference missing; coursework imports need it"
        )
    module_path = str(raw["source"])
    module_graph = modules.get(module_path)
    if module_graph is None:
        raise CurriculumParseError(f"{path}:{pointer}/source: unknown module {module_path}")
    return module_graph


def _mapping(checkout, path: str) -> dict:
    try:
        data = yaml.safe_load(checkout.read_text(path))
    except yaml.YAMLError as error:
        raise CurriculumParseError(f"{path}: invalid YAML: {error}") from None
    if not isinstance(data, dict):
        raise CurriculumParseError(f"{path}: top level must be a mapping")
    return data


def _strict(mapping: dict, path: str, *, allowed: frozenset, required: frozenset) -> None:
    unexpected = set(mapping) - allowed
    if unexpected:
        raise CurriculumParseError(f"{path}: unknown keys {sorted(unexpected)}")
    missing = {
        key
        for key in required
        if mapping.get(key) is None or mapping.get(key) == "" or mapping.get(key) == []
    }
    if missing:
        raise CurriculumParseError(f"{path}: missing keys {sorted(missing)}")


def _schema_version(mapping: dict, path: str) -> None:
    value = mapping.get("schema_version")
    if isinstance(value, bool) or not isinstance(value, int) or value != SCHEMA_VERSION:
        raise CurriculumParseError(f"{path}:/schema_version: expected {SCHEMA_VERSION}")


def _content_id(mapping: dict, path: str, seen: set[str]) -> str:
    value = mapping.get("content_id")
    if not isinstance(value, str) or not value:
        raise CurriculumParseError(f"{path}:/content_id: missing content id")
    _register(value, path, seen)
    return value


def _register(value: str, path: str, seen: set[str]) -> None:
    try:
        UUID(value)
    except ValueError:
        raise CurriculumParseError(f"{path}: content id is not a UUID") from None
    if value in seen:
        raise CurriculumParseError(f"{path}: duplicate content id {value}")
    seen.add(value)


def _sequence(value: Any, path: str, pointer: str, *, minimum: int = 0) -> list:
    if not isinstance(value, list) or len(value) < minimum:
        raise CurriculumParseError(f"{path}:{pointer}: expected a list of at least {minimum}")
    return value


def _text(value, path: str, pointer: str, maximum: int) -> str:
    if not isinstance(value, str) or not value:
        raise CurriculumParseError(f"{path}:{pointer}: expected non-empty text")
    if len(value) > maximum:
        raise CurriculumParseError(f"{path}:{pointer}: text exceeds {maximum} characters")
    return value


def _slug(value, path: str, pointer: str) -> str:
    if not isinstance(value, str) or not _SLUG_RE.fullmatch(value):
        raise CurriculumParseError(f"{path}:{pointer}: invalid slug {value!r}")
    return value


def _https_url(value, path: str, pointer: str) -> str:
    if not isinstance(value, str) or not value.startswith("https://"):
        raise CurriculumParseError(f"{path}:{pointer}: expected an https URL")
    return value


def _optional_date(value, path: str, pointer: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise CurriculumParseError(f"{path}:{pointer}: expected an ISO date")


def _asdict(instance):
    return {item.name: getattr(instance, item.name) for item in fields(instance)}
