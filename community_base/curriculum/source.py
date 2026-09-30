"""The one graph type the course parser produces.

The parser turns a repository layout into :class:`ParsedCurriculum`; the importer
turns that graph into ``cb_curriculum`` rows. The graph knows nothing about
Django, GitHub, or persistence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from community_base.curriculum.project_modules import ProjectModuleBinding

MODE_COHORT = "cohort"
MODE_SELF_PACED = "self_paced"
FORMAT_LEGACY = "legacy"
FORMAT_MODULES = "modules"

ACCESS_NAMES = {
    "open": 0,
    "registered": 5,
    "basic": 10,
    "main": 20,
    "premium": 30,
}


@dataclass(frozen=True, slots=True)
class InstructorGraph:
    name: str
    slug: str | None = None
    bio: str = ""


@dataclass(frozen=True, slots=True)
class UnitGraph:
    content_id: str | None
    slug: str
    title: str
    source_path: str
    body: str = ""
    homework: str = ""
    video_url: str = ""
    timestamps: tuple = field(default=())
    is_preview: bool = False
    required_level: int | None = None
    sort_order: int = 0
    kind: str = "lesson"
    session_position: int | None = None
    is_bonus: bool = False
    source_sibling_position: int | None = None


@dataclass(frozen=True, slots=True)
class ModuleGraph:
    """One course-owned module; ``siblings`` preserves mixed source order."""

    content_id: str | None
    slug: str
    title: str
    source_path: str
    overview: str = ""
    syllabus_section: str = ""
    sort_order: int = 0
    is_bonus: bool = False
    available_after_days: int | None = None
    units: tuple[UnitGraph, ...] = field(default=())
    children: tuple[ModuleGraph, ...] = field(default=())
    source_sibling_position: int | None = None

    @property
    def siblings(self) -> tuple[ModuleGraph | UnitGraph, ...]:
        """Child modules and direct units in their shared authored order."""

        if not self.children:
            return self.units
        if not self.units:
            return self.children
        positioned: list[tuple[int, ModuleGraph | UnitGraph]] = []
        for node in (*self.children, *self.units):
            position = node.source_sibling_position
            if position is None:
                raise CurriculumParseError(f"{self.source_path}: mixed sibling order is missing")
            positioned.append((position, node))
        positioned.sort(key=lambda item: item[0])
        return tuple(node for _, node in positioned)


@dataclass(frozen=True, slots=True)
class CohortGraph:
    content_id: str | None
    slug: str
    title: str
    mode: str = MODE_COHORT
    curriculum_format: str = FORMAT_LEGACY
    start_date: date | None = None
    end_date: date | None = None
    registration_url: str = ""
    hashtag: str = ""
    visible: bool = True
    source_path: str | None = None
    # Ordered top-level module identifiers (content_id, or slug when content_id is
    # None) this cohort places. ``None`` means "the full course tree, in module
    # order" -- a course whose cohorts curate nothing. A non-empty tuple curates a
    # subset or order, DataTalks.Club's case; an empty tuple places nothing, which
    # is what a present ``archive`` mapping means (`FORMAT.md` section 3.8).
    module_refs: tuple[str, ...] | None = None
    # The cohort's homework bindings, ``{module, source, unit}`` each, straight
    # from ``cohort.yaml``. ``module`` is a top-level module slug, ``source`` the
    # manifest path relative to the cohort directory and ``unit`` the optional
    # content id of the unit whose page shows the submission form. The manifests
    # themselves are read by the coursework app (issue C7.11), not here.
    homework_bindings: tuple[Mapping[str, Any], ...] = field(default=())


@dataclass(frozen=True, slots=True)
class CourseGraph:
    content_id: str | None
    slug: str
    title: str
    source_path: str
    description: str = ""
    cover_image_url: str = ""
    required_level: int = 0
    default_unit_required_level: int | None = None
    status: str = "published"
    discussion_url: str = ""
    tags: tuple = field(default=())
    testimonials: tuple = field(default=())
    github_repo_url: str = ""
    docs_url: str = ""
    faq_url: str = ""
    hashtag: str = ""
    visible: bool = True
    instructors: tuple[InstructorGraph, ...] = field(default=())
    # The one module tree, owned by the course. Top-level modules in display
    # order; each may carry ``children`` (submodules, max depth two) and
    # ``units`` directly. ``siblings`` carries their shared source order.
    modules: tuple[ModuleGraph, ...] = field(default=())
    cohorts: tuple[CohortGraph, ...] = field(default=())
    project_modules: tuple[ProjectModuleBinding, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class ParsedCurriculum:
    parser_version: str
    schema_version: int
    commit_sha: str | None
    course: CourseGraph


class CurriculumParseError(ValueError):
    """A repository layout does not satisfy the curriculum source contract."""


def validate_module_tree(modules: tuple[ModuleGraph, ...], *, where: str, depth: int = 1) -> None:
    """Validate a course's module tree once, for the one course parser.

    Enforces a two-level module limit and unambiguous sibling slugs/order.
    """

    seen_module_slugs: set[str] = set()
    for module in modules:
        if module.slug in seen_module_slugs:
            raise CurriculumParseError(f"{where}: duplicate module slug {module.slug!r}")
        seen_module_slugs.add(module.slug)
        module_where = f"{module.source_path or where}"
        _validate_siblings(module, module_where)
        if module.children:
            if depth >= 2:
                raise CurriculumParseError(
                    f"{module_where}: exceeds the maximum module depth of two levels"
                )
            validate_module_tree(module.children, where=module_where, depth=depth + 1)


def _validate_siblings(module: ModuleGraph, where: str) -> None:
    seen_slugs: set[str] = set()
    seen_positions: set[int] = set()
    mixed = bool(module.children and module.units)
    for node in (*module.children, *module.units):
        if node.slug in seen_slugs:
            raise CurriculumParseError(f"{where}: duplicate sibling slug {node.slug!r}")
        seen_slugs.add(node.slug)
        if not mixed:
            continue
        position = node.source_sibling_position
        if position is None:
            raise CurriculumParseError(f"{where}: mixed sibling order is missing")
        if position in seen_positions:
            raise CurriculumParseError(f"{where}: duplicate mixed sibling position {position}")
        seen_positions.add(position)
