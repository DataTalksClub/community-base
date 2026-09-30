"""Public curriculum pages and member (session-authenticated) API views."""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from community_base.api.public_urls import public_url
from community_base.curriculum import services
from community_base.curriculum.access import can_access, gated_reason
from community_base.curriculum.models import Cohort, Course, Unit
from community_base.curriculum.page_context import course_context, module_context, unit_context
from community_base.curriculum.projection import CourseTree
from community_base.curriculum.syllabus import syllabus_payload
from community_base.kernel.access import level_label

SELF_PACED_SLUG = "self-paced"


def _published_courses():
    return Course.objects.filter(status="published", visible=True)


def _self_paced_cohort(course: Course) -> Cohort:
    """Return the course's open-ended cohort, creating it when missing."""

    return services.get_or_create_self_paced_cohort(course)


@require_GET
def course_catalog(request):
    courses = list(_published_courses())
    enrolled_course_ids = set()
    if request.user.is_authenticated:
        enrolled_course_ids = set(
            Course.objects.filter(
                cohorts__enrollments__user=request.user,
                cohorts__enrollments__unenrolled_at__isnull=True,
            ).values_list("pk", flat=True)
        )
    return render(
        request,
        "curriculum/course_catalog.html",
        {"courses": courses, "enrolled_course_ids": enrolled_course_ids},
    )


@require_GET
def course_detail(request, course_slug: str):
    course = get_object_or_404(_published_courses(), slug=course_slug)
    return render(request, "curriculum/course_detail.html", course_context(course, request.user))


def _destination(request, course_slug, cohort_slug, node_path):
    course = get_object_or_404(_published_courses(), slug=course_slug)
    cohort = get_object_or_404(Cohort, course=course, slug=cohort_slug, visible=True)
    projection = CourseTree(course).project(cohort, use_placements=False)
    node = projection.resolve(node_path)
    if node.is_module:
        return render(
            request,
            "curriculum/module_overview.html",
            module_context(projection, node, request.user),
        )
    context = unit_context(projection, node, request.user)
    status = 200
    if context["is_gated"]:
        status = 403
    return render(request, "curriculum/unit_detail.html", context, status=status)


@require_GET
def module_overview(request, course_slug: str, cohort_slug: str, module_slug: str):
    return _destination(request, course_slug, cohort_slug, module_slug)


@require_GET
def unit_detail(request, course_slug: str, cohort_slug: str, module_slug: str, unit_slug: str):
    return _destination(request, course_slug, cohort_slug, f"{module_slug}/{unit_slug}")


@require_GET
def nested_detail(request, course_slug: str, cohort_slug: str, node_path: str):
    return _destination(request, course_slug, cohort_slug, node_path)


@require_POST
@login_required
def course_enroll(request, course_slug: str):
    course = get_object_or_404(_published_courses(), slug=course_slug)
    if not can_access(request.user, course):
        return redirect("curriculum_course_detail", course_slug=course.slug)
    services.ensure_enrollment(request.user, _self_paced_cohort(course))
    return redirect("curriculum_course_detail", course_slug=course.slug)


@require_POST
@login_required
def course_unenroll(request, course_slug: str):
    course = get_object_or_404(_published_courses(), slug=course_slug)
    services.unenroll(request.user, _self_paced_cohort(course))
    return redirect("curriculum_course_detail", course_slug=course.slug)


def _cohort_for(request, course_slug: str, cohort_slug: str, *, allow_hidden=False):
    course = get_object_or_404(_published_courses(), slug=course_slug)
    scope = Cohort.objects.filter(course=course, slug=cohort_slug)
    if not allow_hidden:
        scope = scope.filter(visible=True)
    return course, get_object_or_404(scope)


@require_POST
def cohort_enroll(request, course_slug: str, cohort_slug: str):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=401)
    course, cohort = _cohort_for(request, course_slug, cohort_slug)
    if not can_access(request.user, course):
        return JsonResponse(
            {"error": (f"{level_label(course.required_level)} access required to enroll")},
            status=403,
        )
    if cohort.is_full:
        return JsonResponse({"error": "Cohort is full"}, status=409)
    _enrollment, created = services.ensure_enrollment(request.user, cohort)
    if not created:
        return JsonResponse({"error": "Already enrolled in this cohort"}, status=409)
    return JsonResponse({"enrolled": True, "cohort_id": cohort.pk})


@require_POST
def cohort_unenroll(request, course_slug: str, cohort_slug: str):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=401)
    _course, cohort = _cohort_for(request, course_slug, cohort_slug, allow_hidden=True)
    if not services.unenroll(request.user, cohort):
        return JsonResponse({"error": "Not enrolled in this cohort"}, status=404)
    return JsonResponse({"enrolled": False, "cohort_id": cohort.pk})


# --- member JSON APIs (session authenticated, CSRF protected for POST) ---


def _course_payload(course: Course, user) -> dict:
    primary = course.primary_instructor
    return {
        "id": course.pk,
        "slug": course.slug,
        "title": course.title,
        "description": course.description[:200] if course.description else "",
        "cover_image_url": course.cover_image_url,
        "instructor_name": primary.name if primary else "",
        "instructors": [
            {"slug": host.slug, "name": host.name} for host in course.ordered_instructors
        ],
        "tags": course.tags,
        "is_free": course.is_free,
        "required_level": course.required_level,
        "is_locked": not can_access(user, course),
        "public_url": public_url(course, is_public=course.is_published and course.visible),
    }


@require_GET
def api_courses(request):
    courses = _published_courses()
    return JsonResponse({"courses": [_course_payload(course, request.user) for course in courses]})


@require_GET
def api_course_detail(request, course_slug: str):
    course = get_object_or_404(_published_courses(), slug=course_slug)
    user = request.user
    ordered_instructors = course.ordered_instructors
    primary_bio = ""
    if ordered_instructors:
        primary_bio = ordered_instructors[0].bio
    data = {
        **_course_payload(course, user),
        "description": course.description,
        "instructor_bio": primary_bio,
        "instructors": [
            {"slug": host.slug, "name": host.name, "bio": host.bio, "photo_url": host.photo_url}
            for host in ordered_instructors
        ],
        "discussion_url": course.discussion_url,
        "syllabus": syllabus_payload(course),
    }
    if user.is_authenticated:
        data["progress"] = {
            "completed": course.completed_units(user),
            "total": course.total_units(),
        }
    return JsonResponse(data)


def _gated_unit_response(unit: Unit, user) -> JsonResponse:
    if not user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=401)
    return JsonResponse(
        {
            "error": "Access denied",
            "gated_reason": gated_reason(user, unit) or "insufficient_level",
            "required_level_label": level_label(unit.effective_required_level),
        },
        status=403,
    )


@require_GET
def api_unit_detail(request, course_slug: str, unit_id: int):
    course = get_object_or_404(_published_courses(), slug=course_slug)
    unit = get_object_or_404(Unit, pk=unit_id, module__course=course)
    user = request.user
    if not unit.is_preview and not can_access(user, unit):
        return _gated_unit_response(unit, user)
    data = {
        "id": unit.pk,
        "slug": unit.slug,
        "title": unit.title,
        "sort_order": unit.sort_order,
        "video_url": unit.video_url,
        "body": unit.body,
        "body_html": unit.body_html,
        "homework": unit.homework,
        "homework_html": unit.homework_html,
        "timestamps": unit.timestamps,
        "is_preview": unit.is_preview,
        "module": {
            "id": unit.module.pk,
            "slug": unit.module.slug,
            "title": unit.module.title,
            "sort_order": unit.module.sort_order,
        },
    }
    if user.is_authenticated:
        data["is_completed"] = services.is_completed(user, unit)
    return JsonResponse(data)


@require_POST
def api_unit_complete(request, course_slug: str, unit_id: int):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=401)
    course = get_object_or_404(_published_courses(), slug=course_slug)
    unit = get_object_or_404(Unit, pk=unit_id, module__course=course)
    if not unit.is_preview and not can_access(request.user, unit):
        return JsonResponse({"error": "Access denied"}, status=403)
    if services.is_completed(request.user, unit):
        services.unmark_completed(request.user, unit)
        return JsonResponse({"completed": False})
    services.mark_completed(request.user, unit)
    return JsonResponse({"completed": True})
