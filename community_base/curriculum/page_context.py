"""Prepare generic curriculum pages from the shared cohort projection."""

from django.apps import apps
from django.urls import NoReverseMatch, reverse

from community_base.curriculum import services
from community_base.curriculum.access import can_access, gated_reason
from community_base.curriculum.models import Cohort
from community_base.curriculum.projection import CourseTree, get_syllabus
from community_base.kernel.access import level_label


def _enrolled_cohorts(user, course):
    if not user.is_authenticated:
        return set()
    return set(
        Cohort.objects.filter(
            course=course, enrollments__user=user, enrollments__unenrolled_at__isnull=True
        ).values_list("pk", flat=True)
    )


def _course_progress(course, user, has_access):
    total = course.total_units()
    completed = course.completed_units(user)
    percentage = 0
    if total and has_access:
        percentage = int(completed / total * 100)
    return {"total_units": total, "completed_units": completed, "progress_pct": percentage}


def _continue_node(tree, cohort, user):
    if cohort is None or not user.is_authenticated:
        return None
    projection = tree.project(cohort, use_placements=False)
    completed = services.completed_unit_ids(user, [node.item for node in projection.units])
    return projection.first_unfinished(completed)


def course_context(course, user):
    tree = CourseTree(course)
    cohorts = get_syllabus(course, tree)
    for cohort in cohorts:
        cohort.syllabus_nodes = tree.project(cohort).roots
    default = (
        course.cohorts.filter(mode="self_paced").first()
        or course.cohorts.order_by("start_date", "pk").first()
    )
    enrolled = _enrolled_cohorts(user, course)
    access = can_access(user, course)
    label = ""
    if course.required_level:
        label = level_label(course.required_level)
    return {
        "course": course,
        "cohorts": cohorts,
        "has_access": access,
        "required_level_label": label,
        "user_enrolled_cohort_ids": enrolled,
        "user_is_enrolled": bool(enrolled),
        "default_cohort": default,
        "next_node": _continue_node(tree, default, user),
        **_course_progress(course, user, access),
    }


def module_context(projection, node, user):
    units = [item.item for item in projection.units]
    return {
        "course": projection.tree.course,
        "cohort": projection.cohort,
        "module": node.item,
        "nodes": node.children,
        "breadcrumbs": node.ancestors,
        "has_access": can_access(user, projection.tree.course),
        "completed_unit_ids": services.completed_unit_ids(user, units),
        "user_authenticated": user.is_authenticated,
    }


def bound_homework_context(unit, cohort, user):
    """Keep assignment lookup cohort-owned and optional, with its existing form."""
    if not apps.is_installed("community_base.coursework"):
        return {}
    from community_base.coursework.models import Homework
    from community_base.coursework.submissions import homework_form_context

    homework = Homework.objects.filter(unit=unit, cohort=cohort).first()
    if homework is None:
        return {}
    try:
        action = reverse(
            "coursework_homework", args=[cohort.course.slug, cohort.slug, homework.slug]
        )
    except NoReverseMatch:
        return {}
    return homework_form_context(homework, user, action=action)


def _unit_gate(unit, cohort, user):
    if not unit.is_preview and not can_access(user, unit):
        return {
            "is_gated": True,
            "gated_reason": gated_reason(user, unit) or "insufficient_level",
            "required_level_label": level_label(unit.effective_required_level),
        }
    drip = services.decide_unit_drip(user, unit, cohort)
    if drip.is_locked:
        return {
            "is_gated": True,
            "is_drip_locked": True,
            "drip_available_date": drip.available_date,
        }
    return {"is_gated": False}


def _unit_navigation(projection, node, user):
    units = [row.item for row in projection.units]
    completed = services.completed_unit_ids(user, units)
    previous, following = projection.neighbors(node.item)
    sidebar = projection.units
    for row in projection.entries:
        if row.is_module and row.item.parent_id is not None:
            sidebar = projection.entries
            break
    return {
        "unit_nodes": sidebar,
        "completed_unit_ids": completed,
        "is_completed": node.item.pk in completed,
        "prev_node": previous,
        "next_node": following,
        "completion_url": f"/courses/{projection.tree.course.slug}/units/{node.item.pk}/complete/",
    }


def unit_context(projection, node, user):
    unit = node.item
    context = {
        "course": projection.tree.course,
        "cohort": projection.cohort,
        "module": unit.module,
        "unit": unit,
        "breadcrumbs": node.ancestors,
        "user_authenticated": user.is_authenticated,
        **_unit_gate(unit, projection.cohort, user),
    }
    if not context["is_gated"]:
        context.update(_unit_navigation(projection, node, user))
        context.update(bound_homework_context(unit, projection.cohort, user))
    return context
