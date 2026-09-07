"""Domain services for enrollment, progress and cohort drip scheduling."""

import datetime
from dataclasses import dataclass

from django.utils import timezone

from community_base.curriculum.models import (
    SOURCE_AUTO_PROGRESS,
    SOURCE_MANUAL,
    Cohort,
    Course,
    Enrollment,
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


def is_completed(user, unit: Unit) -> bool:
    if not _is_authenticated(user):
        return False
    return UnitProgress.objects.filter(user=user, unit=unit, completed_at__isnull=False).exists()


def mark_completed(user, unit: Unit, *, when=None):
    """Persist a completion row; idempotent, never refreshes the timestamp.

    Mirrors the donor behavior of auto-enrolling on first completion so the
    learner shows up in their course even when they jumped straight into a
    unit URL.
    """

    if not _is_authenticated(user):
        return None
    when = when or timezone.now()
    progress, _created = UnitProgress.objects.get_or_create(
        user=user, unit=unit, defaults={"completed_at": when}
    )
    ensure_enrollment(user, unit.module.cohort, source=SOURCE_AUTO_PROGRESS)
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


def decide_unit_drip(user, unit: Unit, *, today: datetime.date | None = None) -> DripDecision:
    """Return whether cohort drip scheduling currently locks ``unit``.

    Drip applies only to a dated cohort the user is enrolled in; a unit
    without ``available_after_days``, a self-paced cohort and learners with
    no enrollment are never locked.
    """

    if not _is_authenticated(user) or unit.available_after_days is None:
        return DripDecision(is_locked=False)
    cohort = unit.module.cohort
    if cohort.mode == "self_paced" or cohort.start_date is None:
        return DripDecision(is_locked=False)
    enrollment = Enrollment.objects.filter(user=user, cohort=cohort, unenrolled_at__isnull=True)
    if not enrollment.exists():
        return DripDecision(is_locked=False)
    available_date = cohort.start_date + datetime.timedelta(days=unit.available_after_days)
    today = today or timezone.now().date()
    if today < available_date:
        return DripDecision(is_locked=True, available_date=available_date)
    return DripDecision(is_locked=False, available_date=available_date)


def get_all_units_ordered(course: Course) -> list[Unit]:
    """Return all units of the course in reading order across cohorts."""

    return list(
        Unit.objects.filter(module__cohort__course=course)
        .select_related("module", "module__cohort")
        .order_by("module__sort_order", "sort_order", "pk")
    )


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
