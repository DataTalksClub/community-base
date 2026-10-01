"""Course-specific host adaptation around the package-owned importer."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, fields
from typing import Any, Protocol

from community_base.content_sync.parsers import SourceItem
from community_base.curriculum.source import ParsedCurriculum, UnitGraph

_ACTIONS = frozenset({"created", "updated", "unchanged"})
_COUNT_KEYS = ("created", "updated", "unchanged", "deleted")


class CourseSiteRefusal(ValueError):
    """An authored course is outside the host's accepted policy."""


class CourseSiteBoundaryError(RuntimeError):
    """A host checkout boundary failure that must stop course processing."""


class CourseSitePartialError(RuntimeError):
    """One or more adapted courses failed or produced a warning."""


@dataclass(frozen=True, slots=True)
class CourseSiteContext:
    checkout: object
    source: object
    media: object
    read_result: object


@dataclass(frozen=True, slots=True)
class PreparedCourse:
    curriculum: ParsedCurriculum
    state: object


@dataclass(frozen=True, slots=True)
class CourseCoreResult:
    course: object
    action: str
    counts: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class CourseSiteResult:
    action: str
    counts: Mapping[str, int]
    detail: Mapping[str, Any]
    warnings: tuple[object, ...] = ()


CourseSiteError = tuple[SourceItem, BaseException, bool]


class CourseSiteAdapter(Protocol):
    def prepare(self, context, collection, parsed) -> PreparedCourse: ...

    def apply_scope(self, context, prepared) -> AbstractContextManager[None]: ...

    def after_apply(self, context, prepared, core) -> CourseSiteResult: ...

    def report(
        self,
        context,
        *,
        results: tuple[CourseSiteResult, ...],
        errors: tuple[CourseSiteError, ...],
        drafted: tuple[object, ...],
        totals: Mapping[str, int],
    ) -> None: ...


_adapter: CourseSiteAdapter | None = None


def register_course_site_adapter(adapter: CourseSiteAdapter) -> CourseSiteAdapter:
    """Register the one host adapter; repeat registration is idempotent."""

    global _adapter
    _validate_adapter(adapter)
    if _adapter is not None and _adapter is not adapter:
        raise ValueError("Course site adapter already registered")
    _adapter = adapter
    return adapter


def get_course_site_adapter() -> CourseSiteAdapter | None:
    return _adapter


def _validate_adapter(adapter) -> None:
    for method in ("prepare", "apply_scope", "after_apply", "report"):
        if not callable(getattr(adapter, method, None)):
            raise TypeError(f"Course site adapter must implement {method}()")


def validate_prepared_course(original, prepared) -> None:
    """Allow render text changes while retaining every structural identity."""

    if not isinstance(prepared, PreparedCourse):
        raise TypeError("Course site prepare() must return PreparedCourse")
    candidate = prepared.curriculum
    if not isinstance(candidate, ParsedCurriculum):
        raise TypeError("PreparedCourse.curriculum must be ParsedCurriculum")
    _require_equal_fields(original, candidate, {"course"}, "curriculum")
    _validate_course(original.course, candidate.course)


def _validate_course(original, candidate) -> None:
    _require_equal_fields(original, candidate, {"cover_image_url", "modules"}, "course")
    _require_same_length(original.modules, candidate.modules, "course modules")
    for index, original_module in enumerate(original.modules):
        _validate_module(original_module, candidate.modules[index])


def _validate_module(original, candidate) -> None:
    ignored = {"overview", "units", "children"}
    _require_equal_fields(original, candidate, ignored, f"module {original.slug!r}")
    _require_same_length(original.units, candidate.units, f"module {original.slug!r} units")
    for index, original_unit in enumerate(original.units):
        _validate_unit(original_unit, candidate.units[index])
    label = f"module {original.slug!r} children"
    _require_same_length(original.children, candidate.children, label)
    for index, original_child in enumerate(original.children):
        _validate_module(original_child, candidate.children[index])


def _validate_unit(original: UnitGraph, candidate: UnitGraph) -> None:
    _require_equal_fields(original, candidate, {"body", "homework"}, f"unit {original.slug!r}")


def _require_equal_fields(original, candidate, ignored, label) -> None:
    if type(original) is not type(candidate):
        raise ValueError(f"Course site adapter changed {label} type")
    for field in fields(original):
        if field.name in ignored:
            continue
        if getattr(original, field.name) != getattr(candidate, field.name):
            raise ValueError(f"Course site adapter changed {label} field {field.name!r}")


def _require_same_length(original, candidate, label) -> None:
    if len(original) != len(candidate):
        raise ValueError(f"Course site adapter changed {label}")


def validate_site_result(result) -> None:
    if not isinstance(result, CourseSiteResult):
        raise TypeError("Course site after_apply() must return CourseSiteResult")
    if result.action not in _ACTIONS:
        raise ValueError(f"Unknown course site action: {result.action}")
    _validate_counts(result.counts)


def _validate_counts(counts) -> None:
    if not isinstance(counts, Mapping):
        raise TypeError("Course site counts must be a mapping")
    for key, value in counts.items():
        if key not in _COUNT_KEYS:
            raise ValueError(f"Unknown course site count: {key}")
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"Course site count {key!r} must be a non-negative integer")


def merged_counts(*groups) -> dict[str, int]:
    counts = {key: 0 for key in _COUNT_KEYS}
    for group in groups:
        for key, value in group.items():
            counts[key] += value
    return counts


def merged_action(*actions) -> str:
    for action in actions:
        if action not in _ACTIONS:
            raise ValueError(f"Unknown course site action: {action}")
    if "created" in actions:
        return "created"
    if "updated" in actions:
        return "updated"
    return "unchanged"


def counts_action(counts) -> str:
    if counts.get("created"):
        return "created"
    if counts.get("updated") or counts.get("deleted"):
        return "updated"
    return "unchanged"


def _clear_course_site_adapter() -> None:
    """Reset the registration only for isolated registry tests."""

    global _adapter
    _adapter = None
