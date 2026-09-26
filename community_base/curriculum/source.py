"""The one graph type the course parser produces.

The parser turns a repository layout into :class:`ParsedCurriculum`; the importer
turns that graph into ``cb_curriculum`` rows. The graph knows nothing about
Django, GitHub, or persistence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

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
    available_after_days: int | None = None
    body_source_path: str | None = None
    has_order: bool = False
    homework_unit: HomeworkUnitGraph | None = None


@dataclass(frozen=True, slots=True)
class HomeworkOptionGraph:
    id: str
    label: str


@dataclass(frozen=True, slots=True)
class HomeworkQuestionGraph:
    content_id: str
    stable_id: str
    type: str
    prompt: str
    points: int
    options: tuple[HomeworkOptionGraph, ...] = field(default=())
    answer_type: str | None = None
    step_label: str = ""
    correct: str | None = None


@dataclass(frozen=True, slots=True)
class HomeworkFormGraph:
    homework_url: bool | None = None
    time_spent_lectures: bool | None = None
    time_spent_homework: bool | None = None
    faq_contribution: bool | None = None
    learning_in_public_cap: int | None = None


@dataclass(frozen=True, slots=True)
class HomeworkFinalFieldGraph:
    key: str
    label: str
    type: str = "text"
    required: bool = False


@dataclass(frozen=True, slots=True)
class HomeworkUnitGraph:
    due_at: datetime
    form: HomeworkFormGraph = field(default_factory=HomeworkFormGraph)
    questions: tuple[HomeworkQuestionGraph, ...] = field(default=())
    final_fields: tuple[HomeworkFinalFieldGraph, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class ModuleGraph:
    """One physical module and its ordered, mixed child sequence."""

    content_id: str | None
    slug: str
    title: str
    source_path: str
    overview: str = ""
    syllabus_section: str = ""
    sort_order: int = 0
    is_bonus: bool = False
    available_after_days: int | None = None
    has_order: bool = False
    items: tuple[ModuleGraph | UnitGraph, ...] = field(default=())

    @property
    def units(self) -> tuple[UnitGraph, ...]:
        """Direct units in sibling order, retained for older read-only consumers."""

        return tuple(item for item in self.items if isinstance(item, UnitGraph))

    @property
    def children(self) -> tuple[ModuleGraph, ...]:
        """Child modules in sibling order, retained for older read-only consumers."""

        return tuple(item for item in self.items if isinstance(item, ModuleGraph))


@dataclass(frozen=True, slots=True)
class ProjectGraph:
    slug: str
    title: str
    module_path: str
    module_content_id: str | None
    submission_due_at: datetime
    review_due_at: datetime
    cohort_key: str | None = None
    peer_review_count: int | None = None


@dataclass(frozen=True, slots=True)
class CourseTreeGraph:
    """Physical course content without course-, cohort- or site-owned metadata.

    Site adapters for legacy course repositories use this graph to parse the
    checked-in module/unit tree while retaining ownership of their existing
    course headers and cohort policy.
    """

    parser_version: str
    schema_version: int
    source_path: str
    modules: tuple[ModuleGraph, ...] = field(default=())
    projects: tuple[ProjectGraph, ...] = field(default=())


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
    projects: tuple[ProjectGraph, ...] = field(default=())
    # The one module tree, owned by the course. Top-level modules and every
    # module's `items` preserve the physical mixed sibling order.
    modules: tuple[ModuleGraph, ...] = field(default=())
    cohorts: tuple[CohortGraph, ...] = field(default=())


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

    Enforces unique sibling slugs and orders across the mixed module/unit sequence,
    explicit ordering for every sibling, and the existing two-level module bound.
    """

    seen_module_slugs: set[str] = set()
    seen_module_orders: set[int] = set()
    for module in modules:
        if module.slug in seen_module_slugs:
            raise CurriculumParseError(f"{where}: duplicate module slug {module.slug!r}")
        seen_module_slugs.add(module.slug)
        module_where = f"{module.source_path or where}"
        if not module.has_order:
            raise CurriculumParseError(
                f"{module_where}: missing sibling order; declare sort_order or use an NN- prefix"
            )
        if module.sort_order in seen_module_orders:
            raise CurriculumParseError(
                f"{module_where}: duplicate sibling order {module.sort_order}"
            )
        seen_module_orders.add(module.sort_order)
        seen_sibling_slugs: set[str] = set()
        seen_orders: set[int] = set()
        for sibling in module.items:
            sibling_where = sibling.source_path or module_where
            if sibling.slug in seen_sibling_slugs:
                raise CurriculumParseError(
                    f"{sibling_where}: duplicate sibling slug {sibling.slug!r}"
                )
            seen_sibling_slugs.add(sibling.slug)
            if not sibling.has_order:
                raise CurriculumParseError(
                    f"{sibling_where}: missing sibling order; declare sort_order or use an "
                    "NN- prefix"
                )
            if sibling.sort_order in seen_orders:
                raise CurriculumParseError(
                    f"{sibling_where}: duplicate sibling order {sibling.sort_order}"
                )
            seen_orders.add(sibling.sort_order)
            if isinstance(sibling, UnitGraph) and sibling.homework_unit:
                validate_homework_unit(sibling.homework_unit, where=sibling_where)
        children = module.children
        if children:
            if depth >= 2:
                raise CurriculumParseError(
                    f"{module_where}: exceeds the maximum module depth of two levels"
                )
            validate_module_tree(children, where=module_where, depth=depth + 1)


def validate_homework_unit(homework: HomeworkUnitGraph, *, where: str) -> None:
    """Validate question identities, choice shapes and legacy scoring values."""

    seen_question_ids: set[str] = set()
    seen_content_ids: set[str] = set()
    for index, question in enumerate(homework.questions):
        pointer = f"{where}:/questions/{index}"
        if question.stable_id in seen_question_ids:
            raise CurriculumParseError(
                f"{pointer}/id: duplicate question id {question.stable_id!r}"
            )
        if question.content_id in seen_content_ids:
            raise CurriculumParseError(
                f"{pointer}/content_id: duplicate question content_id {question.content_id!r}"
            )
        seen_question_ids.add(question.stable_id)
        seen_content_ids.add(question.content_id)
        option_ids = [option.id for option in question.options]
        if len(option_ids) != len(set(option_ids)):
            raise CurriculumParseError(f"{pointer}/options: duplicate option id")
        choice = question.type in {"multiple_choice", "checkboxes"}
        if choice and not question.options:
            raise CurriculumParseError(f"{pointer}/options: choice questions need ordered options")
        if not choice and question.options:
            raise CurriculumParseError(
                f"{pointer}/options: free-form questions do not take options"
            )
        if question.correct is not None and choice:
            try:
                indexes = [int(item.strip()) for item in question.correct.split(",")]
            except (TypeError, ValueError):
                raise CurriculumParseError(
                    f"{pointer}/correct: choice answers use 1-based option indexes"
                ) from None
            if (
                not indexes
                or any(
                    index_value < 1 or index_value > len(question.options)
                    for index_value in indexes
                )
                or len(set(indexes)) != len(indexes)
                or (question.type == "multiple_choice" and len(indexes) != 1)
            ):
                raise CurriculumParseError(
                    f"{pointer}/correct: answer index must identify an authored option"
                )
        if question.points < 0:
            raise CurriculumParseError(f"{pointer}/points: must be zero or a positive integer")
