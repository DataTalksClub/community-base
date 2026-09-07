"""The one graph type both curriculum parsers produce.

Parsers turn a repository layout into :class:`ParsedCurriculum`; the importer
turns that graph into ``cb_curriculum`` rows. The graph knows nothing about
Django, GitHub, or persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

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


@dataclass(frozen=True, slots=True)
class ModuleGraph:
    content_id: str | None
    slug: str
    title: str
    source_path: str
    overview: str = ""
    sort_order: int = 0
    units: tuple[UnitGraph, ...] = field(default=())


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
    modules: tuple[ModuleGraph, ...] = field(default=())


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
    cohorts: tuple[CohortGraph, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class ParsedCurriculum:
    parser_version: str
    schema_version: int
    commit_sha: str | None
    course: CourseGraph


class CurriculumParseError(ValueError):
    """A repository layout does not satisfy the curriculum source contract."""
