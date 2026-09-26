"""Domain services for enrollment, progress and cohort drip scheduling."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class UnitProjection:
    """A persisted unit at its source-derived position in the physical tree."""

    unit: Unit
    path: str
    module_path: str
    depth: int
    kind: str = "unit"


@dataclass(frozen=True, slots=True)
class ModuleProjection:
    """A persisted module with mixed, ordered module/unit child projections.

    ``descendant_unit_count`` includes direct units as well as units below child
    modules. ``descendant_module_count`` counts child modules, not this module.
    Child module items are recursively projected ModuleProjection objects.
    """

    module: Module
    items: tuple[ModuleProjection | UnitProjection, ...]
    path: str
    depth: int
    direct_unit_count: int
    descendant_unit_count: int
    descendant_module_count: int
    kind: str = "module"

    @property
    def level(self) -> int:
        """The human-facing level, with top-level modules at level one."""

        return self.depth + 1

    @property
    def all_units(self) -> tuple[UnitProjection, ...]:
        """Return every unit below this module in reading order."""

        return tuple(
            nested
            for item in self.items
            for nested in (item.all_units if isinstance(item, ModuleProjection) else (item,))
        )


def get_curriculum_tree(
    course: Course,
    modules=None,
) -> tuple[ModuleProjection, ...]:
    """Project a course's physical module tree with every mixed level preserved.

    Pass ``modules`` to project a cohort's already ordered top-level selection;
    child modules and direct units remain in the shared source order. This
    projection contains learner-facing curriculum fields only and never carries
    homework scoring metadata.
    """

    all_modules = list(Module.objects.filter(course=course).order_by("sort_order", "pk"))
    all_units = list(
        Unit.objects.filter(module__course=course)
        .select_related("module")
        .order_by("sort_order", "pk")
    )
    modules_by_parent: dict[int | None, list[Module]] = {}
    modules_by_id: dict[int, Module] = {}
    for module in all_modules:
        modules_by_parent.setdefault(module.parent_id, []).append(module)
        modules_by_id[module.pk] = module
    units_by_module: dict[int, list[Unit]] = {}
    for unit in all_units:
        units_by_module.setdefault(unit.module_id, []).append(unit)

    def item_key(item):
        # Unit and Module tables have independent primary-key sequences. The
        # type tag closes the rare tie while normal source siblings use one
        # unique sort_order across both types.
        return (item.sort_order, item.pk, 0 if isinstance(item, Unit) else 1)

    def project(module: Module, parent_path: str, depth: int) -> ModuleProjection:
        path = f"{parent_path}/{module.slug}" if parent_path else module.slug
        direct_units = units_by_module.get(module.pk, [])
        child_modules = modules_by_parent.get(module.pk, [])
        projected_children = {child.pk: project(child, path, depth + 1) for child in child_modules}
        physical_items = [*direct_units, *child_modules]
        physical_items.sort(key=item_key)
        items: list[ModuleProjection | UnitProjection] = []
        descendant_unit_count = 0
        descendant_module_count = len(child_modules)
        for item in physical_items:
            if isinstance(item, Unit):
                items.append(
                    UnitProjection(
                        unit=item,
                        path=f"{path}/{item.slug}",
                        module_path=path,
                        depth=depth,
                    )
                )
                descendant_unit_count += 1
            else:
                child = projected_children[item.pk]
                items.append(child)
                descendant_unit_count += child.descendant_unit_count
                descendant_module_count += child.descendant_module_count
        return ModuleProjection(
            module=module,
            items=tuple(items),
            path=path,
            depth=depth,
            direct_unit_count=len(direct_units),
            descendant_unit_count=descendant_unit_count,
            descendant_module_count=descendant_module_count,
        )

    selected_modules = list(modules) if modules is not None else modules_by_parent.get(None, [])

    def parent_context(module: Module) -> tuple[str, int]:
        ancestors = []
        parent_id = module.parent_id
        while parent_id is not None:
            parent = modules_by_id[parent_id]
            ancestors.append(parent.slug)
            parent_id = parent.parent_id
        ancestors.reverse()
        return "/".join(ancestors), len(ancestors)

    return tuple(project(module, *parent_context(module)) for module in selected_modules)


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
    """Return every unit in depth-first, mixed sibling source order."""

    return [item.unit for module in get_curriculum_tree(course) for item in module.all_units]


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
