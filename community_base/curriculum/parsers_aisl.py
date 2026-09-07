"""Parser for the AISL ``course.yaml`` repository layout.

Layout (one directory per course anywhere in the checkout):

- ``<course-dir>/course.yaml`` - course metadata
- ``<course-dir>/<module-dir>/module.yaml`` - module metadata
- ``<course-dir>/<module-dir>/<NN>-<slug>.md`` - unit content with frontmatter
- ``<course-dir>/README.md`` - course description when ``course.yaml`` has none
- ``<course-dir>/<module-dir>/README.md`` - module overview

Every course becomes one open-ended self-paced cohort, because the shared
model requires every course to have at least one cohort.
"""

from __future__ import annotations

import re

import yaml

from community_base.content_sync.checkout import CheckoutError
from community_base.curriculum.source import (
    ACCESS_NAMES,
    FORMAT_MODULES,
    MODE_SELF_PACED,
    CohortGraph,
    CourseGraph,
    CurriculumParseError,
    InstructorGraph,
    ModuleGraph,
    ParsedCurriculum,
    UnitGraph,
)

PARSER_VERSION = "aisl-course-yaml-1"
SCHEMA_VERSION = 1

_LEADING_H1_RE = re.compile(r"^#\s+(.+?)\s*#*\s*$")
_SELF_PACED_SLUG = "self-paced"


def parse_aisl_course(checkout, course_yaml_path: str) -> ParsedCurriculum:
    """Parse one AISL course directory into the shared graph."""

    raw = checkout.read_text(course_yaml_path)
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as error:
        raise CurriculumParseError(f"{course_yaml_path}: invalid YAML: {error}") from None
    if not isinstance(data, dict):
        raise CurriculumParseError(f"{course_yaml_path}: top level must be a mapping")

    directory = course_yaml_path.rsplit("/", 1)[0]
    slug = str(data.get("slug") or directory.rsplit("/", 1)[-1])
    title = str(data.get("title") or slug)
    content_id = str(data.get("content_id") or "") or None
    description = str(data.get("description") or "")
    if not description:
        description = _read_body(checkout, f"{directory}/README.md")

    default_unit_level = _access_value(
        data.get("default_unit_access"),
        f"{course_yaml_path}:/default_unit_access",
    )

    instructors = []
    for index, entry in enumerate(data.get("instructors") or []):
        if not isinstance(entry, dict) or not entry.get("name"):
            raise CurriculumParseError(
                f"{course_yaml_path}:/instructors/{index}: each instructor needs a name"
            )
        instructors.append(
            InstructorGraph(
                name=str(entry["name"]),
                slug=str(entry.get("id") or entry.get("instructor_id") or "") or None,
                bio=str(entry.get("bio") or ""),
            )
        )

    modules = tuple(
        _parse_module(checkout, directory, entry) for entry in _module_entries(checkout, directory)
    )
    self_paced = CohortGraph(
        content_id=None,
        slug=_SELF_PACED_SLUG,
        title=f"{title} (self-paced)",
        mode=MODE_SELF_PACED,
        curriculum_format=FORMAT_MODULES,
        start_date=None,
        end_date=None,
        source_path=course_yaml_path,
        modules=modules,
    )

    course = CourseGraph(
        content_id=content_id,
        slug=slug,
        title=title,
        source_path=course_yaml_path,
        description=description,
        cover_image_url=str(data.get("cover_image_url") or data.get("cover_image") or ""),
        required_level=_int(data.get("required_level"), 0, f"{course_yaml_path}:/required_level"),
        default_unit_required_level=default_unit_level,
        status="published",
        discussion_url=str(data.get("discussion_url") or ""),
        tags=tuple(data.get("tags") or ()),
        testimonials=tuple(data.get("testimonials") or ()),
        github_repo_url=str(data.get("github_repo_url") or data.get("repository_url") or ""),
        docs_url=str(data.get("docs_url") or ""),
        faq_url=str(data.get("faq_url") or ""),
        hashtag=str(data.get("hashtag") or ""),
        visible=True,
        instructors=tuple(instructors),
        cohorts=(self_paced,),
    )
    return ParsedCurriculum(
        parser_version=PARSER_VERSION,
        schema_version=SCHEMA_VERSION,
        commit_sha=checkout.commit_sha or None,
        course=course,
    )


def _module_entries(checkout, directory: str) -> list[tuple[str, dict]]:
    prefix = tuple(directory.split("/"))
    module_depth = len(prefix) + 2
    entries = []
    for path in checkout.files():
        parts = path.parts
        if (
            len(parts) == module_depth
            and parts[: len(prefix)] == prefix
            and parts[-1] == "module.yaml"
        ):
            module_dir = "/".join(parts[:-1])
            try:
                data = yaml.safe_load(checkout.read_text(path.as_posix())) or {}
            except yaml.YAMLError as error:
                raise CurriculumParseError(f"{path}: invalid YAML: {error}") from None
            if not isinstance(data, dict):
                raise CurriculumParseError(f"{path}: top level must be a mapping")
            entries.append((module_dir, data))
    entries.sort(key=lambda entry: (_module_sort(entry[0], entry[1]), entry[0]))
    return entries


def _module_sort(module_dir: str, data: dict) -> int:
    configured = data.get("sort_order")
    if configured is not None:
        return _int(configured, 0, f"{module_dir}/module.yaml:/sort_order")
    return _prefix_sort(module_dir.rsplit("/", 1)[-1])


def _parse_module(checkout, directory: str, entry: tuple[str, dict]) -> ModuleGraph:
    module_dir, data = entry
    prefix = tuple(directory.split("/"))
    dir_name = module_dir.rsplit("/", 1)[-1]
    module_path = f"{module_dir}/module.yaml"
    slug = str(data.get("slug") or _derive_slug(dir_name))
    title = str(data.get("title") or _derive_slug(dir_name))
    overview = _read_body(checkout, f"{module_dir}/README.md")

    units = []
    unit_depth = len(prefix) + 2
    for path in checkout.files():
        parts = path.parts
        if len(parts) != unit_depth or parts[: len(prefix)] != prefix or parts[-2] != dir_name:
            continue
        name = parts[-1]
        if not name.endswith(".md") or name.lower() == "readme.md" or name.startswith("."):
            continue
        units.append(_parse_unit(checkout, module_dir, path.as_posix(), name))
    units.sort(key=lambda unit: (unit.sort_order, unit.slug))

    return ModuleGraph(
        content_id=str(data.get("content_id") or "") or None,
        slug=slug,
        title=title,
        source_path=module_path,
        overview=overview,
        sort_order=_module_sort(module_dir, data),
        units=tuple(units),
    )


def _parse_unit(checkout, module_dir: str, path: str, name: str) -> UnitGraph:
    raw = checkout.read_text(path)
    frontmatter, body = _split_frontmatter(path, raw)
    if not frontmatter.get("content_id"):
        raise CurriculumParseError(f"{path}: missing content_id in frontmatter")

    is_homework = bool(frontmatter.get("is_homework", False))
    access_raw = frontmatter.get("access")
    required_level = (
        _access_value(access_raw, f"{path}:/access") if access_raw is not None else None
    )
    is_preview = bool(frontmatter.get("is_preview", False))
    title = str(frontmatter.get("title") or _derive_slug(name.rsplit(".", 1)[0]))

    return UnitGraph(
        content_id=str(frontmatter["content_id"]),
        slug=str(frontmatter.get("slug") or _derive_slug(name.rsplit(".", 1)[0])),
        title=title,
        source_path=path,
        body="" if is_homework else body,
        homework=body if is_homework else "",
        video_url=str(frontmatter.get("video_url") or ""),
        timestamps=tuple(frontmatter.get("timestamps") or ()),
        is_preview=is_preview,
        required_level=required_level,
        sort_order=_int(frontmatter.get("sort_order"), _prefix_sort(name), f"{path}:/sort_order"),
    )


def _split_frontmatter(path: str, raw: str) -> tuple[dict, str]:
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise CurriculumParseError(f"{path}: unit files require frontmatter")
    closing = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            closing = index
            break
    if closing is None:
        raise CurriculumParseError(f"{path}: frontmatter is not closed")
    try:
        data = yaml.safe_load("".join(lines[1:closing])) or {}
    except yaml.YAMLError as error:
        raise CurriculumParseError(f"{path}: invalid frontmatter: {error}") from None
    if not isinstance(data, dict):
        raise CurriculumParseError(f"{path}: frontmatter must be a mapping")
    body = "".join(lines[closing + 1 :]).lstrip("\n")
    return data, body


def _read_body(checkout, path: str) -> str:
    try:
        raw = checkout.read_text(path)
    except CheckoutError:
        return ""
    _, body = _split_optional_frontmatter(raw)
    return body


def _split_optional_frontmatter(raw: str) -> tuple[dict, str]:
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, raw
    closing = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            closing = index
            break
    if closing is None:
        return {}, raw
    try:
        data = yaml.safe_load("".join(lines[1:closing])) or {}
    except yaml.YAMLError:
        return {}, raw
    return (data if isinstance(data, dict) else {}), "".join(lines[closing + 1 :]).lstrip("\n")


def _access_value(raw, where: str) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        raise CurriculumParseError(f"{where}: access cannot be a boolean")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        name = raw.strip().lower()
        if name in ACCESS_NAMES:
            return ACCESS_NAMES[name]
        if name.isdigit():
            return int(name)
    raise CurriculumParseError(f"{where}: unknown access value {raw!r}")


def _int(value, default, where: str) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise CurriculumParseError(f"{where}: expected an integer, got {value!r}")
    return value


def _prefix_sort(name: str) -> int:
    match = re.match(r"^(\d+)", name)
    return int(match.group(1)) if match else 0


def _derive_slug(name: str) -> str:
    stem = name.rsplit(".", 1)[0] if "." in name else name
    match = re.match(r"^\d+-(.+)", stem)
    slug = match.group(1) if match else stem
    return re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-") or "unit"
