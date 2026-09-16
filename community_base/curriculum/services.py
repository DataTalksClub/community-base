"""Domain services for enrollment, progress and cohort drip scheduling."""

import datetime
from dataclasses import dataclass

from django.db.models import Prefetch
from django.utils import timezone

from community_base.curriculum.models import (
    SOURCE_AUTO_PROGRESS,
    SOURCE_MANUAL,
    UNIT_KIND_CHECKLIST_ITEM,
    Cohort,
    Course,
    Enrollment,
    Module,
    Unit,
    UnitProgress,
)


def _is_authenticated(user) -> bool:
    return user is not None and getattr(user, "is_authenticated", False)


def get_active_enrollment(user, cohort: Cohort):
    if not _is_authenticated(user):
        return None
    return Enrollment.objects.filter(user=user, cohort=cohort, unenrolled_at__isnull=True).first()


def is_enrolled(user, cohort: Cohort) -> bool:
    return get_active_enrollment(user, cohort) is not None


def ensure_enrollment(user, cohort: Cohort, source: str = SOURCE_MANUAL):
    """Create an active enrollment unless one exists. Returns (enrollment, created)."""

    if not _is_authenticated(user):
        return None, False
    existing = get_active_enrollment(user, cohort)
    if existing is not None:
        return existing, False
    return (
        Enrollment.objects.create(user=user, cohort=cohort, source=source),
        True,
    )


def unenroll(user, cohort: Cohort) -> bool:
    """Soft-delete the active enrollment. Returns True if anything changed."""

    enrollment = get_active_enrollment(user, cohort)
    if enrollment is None:
        return False
    enrollment.unenrolled_at = timezone.now()
    enrollment.save(update_fields=["unenrolled_at"])
    return True


def get_or_create_self_paced_cohort(course: Course) -> Cohort:
    """Return the course's open-ended self-paced cohort, creating it when missing.

    Curriculum is course-owned; the self-paced cohort is the default enrollment and
    completion target when a caller has no more specific cohort in view (for example a
    unit completion toggle reached from a cohort-free URL).
    """

    cohort = course.cohorts.filter(mode="self_paced").first()
    if cohort is None:
        cohort = Cohort.objects.create(
            course=course,
            slug="self-paced",
            title=f"{course.title} (self-paced)",
            mode="self_paced",
        )
    return cohort


def is_completed(user, unit: Unit) -> bool:
    if not _is_authenticated(user):
        return False
    return UnitProgress.objects.filter(user=user, unit=unit, completed_at__isnull=False).exists()


def mark_completed(user, unit: Unit, *, cohort: Cohort | None = None, when=None):
    """Persist a completion row; idempotent, never refreshes the timestamp.

    Mirrors the donor behavior of auto-enrolling on first completion so the learner shows
    up in their course even when they jumped straight into a unit URL. ``cohort`` is the
    viewer's cohort when known; without one (curriculum is course-owned, so a unit has no
    single cohort of its own) the course's self-paced cohort is the enrollment target.
    """

    if not _is_authenticated(user):
        return None
    when = when or timezone.now()
    progress, _created = UnitProgress.objects.get_or_create(
        user=user, unit=unit, defaults={"completed_at": when}
    )
    target_cohort = cohort or get_or_create_self_paced_cohort(unit.course)
    ensure_enrollment(user, target_cohort, source=SOURCE_AUTO_PROGRESS)
    return progress


def unmark_completed(user, unit: Unit) -> bool:
    if not _is_authenticated(user):
        return False
    deleted, _ = UnitProgress.objects.filter(user=user, unit=unit).delete()
    return bool(deleted)


def completed_unit_ids(user, units) -> set[int]:
    """Batched read: the ids of ``units`` the user has completed."""

    if not _is_authenticated(user):
        return set()
    ids = [unit.pk for unit in units]
    if not ids:
        return set()
    return set(
        UnitProgress.objects.filter(
            user=user, unit_id__in=ids, completed_at__isnull=False
        ).values_list("unit_id", flat=True)
    )


@dataclass(frozen=True)
class DripDecision:
    """Drip-schedule decision after tier/unit access has been granted."""

    is_locked: bool
    available_date: datetime.date | None = None


def decide_unit_drip(
    user, unit: Unit, cohort: Cohort, *, today: datetime.date | None = None
) -> DripDecision:
    """Return whether cohort drip scheduling currently locks ``unit`` for ``cohort``.

    Curriculum is course-owned, so a unit's drip decision depends on which cohort is
    viewing it -- ``cohort`` must be supplied explicitly rather than resolved from the
    unit. Drip applies only to a dated cohort the user is enrolled in; a unit (or its
    module, or that module's parent module -- see ``Unit.effective_available_after_days``)
    with no offset at all, a self-paced cohort, and a learner with no enrollment are never
    locked.
    """

    if not _is_authenticated(user):
        return DripDecision(is_locked=False)
    offset = unit.effective_available_after_days
    if offset is None:
        return DripDecision(is_locked=False)
    if cohort.mode == "self_paced" or cohort.start_date is None:
        return DripDecision(is_locked=False)
    enrollment = Enrollment.objects.filter(user=user, cohort=cohort, unenrolled_at__isnull=True)
    if not enrollment.exists():
        return DripDecision(is_locked=False)
    available_date = cohort.start_date + datetime.timedelta(days=offset)
    today = today or timezone.now().date()
    if today < available_date:
        return DripDecision(is_locked=True, available_date=available_date)
    return DripDecision(is_locked=False, available_date=available_date)


def get_all_units_ordered(course: Course) -> list[Unit]:
    """Return every unit of the course in depth-first reading order.

    For each top-level module, in ``sort_order``: if it has submodules, each submodule's
    units in order; otherwise the module's own units directly -- a module holds either
    children or units, never both (community-base#252). ``id`` is an explicit tiebreaker
    after ``sort_order``, which is not unique.
    """

    top_modules = list(
        Module.objects.filter(course=course, parent__isnull=True)
        .prefetch_related(
            Prefetch("children", queryset=Module.objects.order_by("sort_order", "pk")),
            Prefetch("units", queryset=Unit.objects.order_by("sort_order", "pk")),
        )
        .order_by("sort_order", "pk")
    )
    child_ids = [child.pk for module in top_modules for child in module.children.all()]
    units_by_module: dict[int, list[Unit]] = {}
    if child_ids:
        for unit in Unit.objects.filter(module_id__in=child_ids).order_by(
            "module_id", "sort_order", "pk"
        ):
            units_by_module.setdefault(unit.module_id, []).append(unit)

    ordered: list[Unit] = []
    for module in top_modules:
        children = list(module.children.all())
        if children:
            for child in children:
                ordered.extend(units_by_module.get(child.pk, []))
        else:
            ordered.extend(module.units.all())
    return ordered


def get_next_unit(course: Course, current_unit: Unit):
    units = get_all_units_ordered(course)
    for index, unit in enumerate(units):
        if unit.pk == current_unit.pk:
            return units[index + 1] if index + 1 < len(units) else None
    return None


def get_prev_unit(course: Course, current_unit: Unit):
    units = get_all_units_ordered(course)
    for index, unit in enumerate(units):
        if unit.pk == current_unit.pk:
            return units[index - 1] if index > 0 else None
    return None


def get_next_unit_for_user(course: Course, user):
    """Return the first unfinished unit in reading order, or None."""

    if not _is_authenticated(user):
        return None
    units = get_all_units_ordered(course)
    if not units:
        return None
    completed = completed_unit_ids(user, units)
    for unit in units:
        if unit.pk not in completed:
            return unit
    return None


def get_checklist_items(module: Module) -> list[Unit]:
    """Return ``module``'s checklist items (``kind=checklist_item``) in reading order."""

    return list(module.units.filter(kind=UNIT_KIND_CHECKLIST_ITEM).order_by("sort_order", "pk"))


@dataclass(frozen=True)
class ChecklistItemState:
    """One checklist item with its per-learner completion state.

    ``is_required`` mirrors the unit's ``is_bonus`` flag: a required item has
    ``is_bonus=False``, an optional item has ``is_bonus=True`` -- the same field the rest of
    curriculum already uses for "optional, tracked and displayed but not required".
    """

    unit: Unit
    is_required: bool
    is_completed: bool


def get_checklist_state(user, module: Module) -> list[ChecklistItemState]:
    """Return ``module``'s checklist items with ``user``'s completion state for each."""

    items = get_checklist_items(module)
    completed = completed_unit_ids(user, items)
    return [
        ChecklistItemState(
            unit=item,
            is_required=not item.is_bonus,
            is_completed=item.pk in completed,
        )
        for item in items
    ]
