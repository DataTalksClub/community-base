"""Member API endpoints for coursework learner flows.

Restores the C5.2dc member-API surface: the donor exposes the leaderboard
through the public ``leaderboard.yaml`` export and toggles display preferences
through the enrollment page form; the package additionally serves both over the
API registry so site clients can reuse them without scraping HTML.
"""

from community_base.api import route
from community_base.api.errors import APIError
from community_base.api.registry import json_response
from community_base.api.safety import read_json_object
from community_base.coursework import leaderboard
from community_base.curriculum.models import Cohort, Enrollment

PREFERENCE_REQUEST = {
    "type": "object",
    "properties": {"field": {"type": "string"}, "value": {"type": "string"}},
    "required": ["field", "value"],
}
PREFERENCE_RESPONSE = {
    "type": "object",
    "properties": {
        "changed": {"type": "boolean"},
        "enabled": {"type": "boolean"},
        "enrollment": {"type": "object"},
        "field": {"type": "string"},
    },
    "required": ["enrollment", "field", "enabled", "changed"],
}
LEADERBOARD_RESPONSE = {
    "type": "object",
    "properties": {
        "count": {"type": "integer"},
        "leaderboard": {"type": "array", "items": {"type": "object"}},
        "page": {"type": "integer"},
        "page_size": {"type": "integer"},
    },
    "required": ["leaderboard", "page", "page_size", "count"],
}


def _cohort(course_slug, cohort_slug) -> Cohort:
    cohort = Cohort.objects.filter(course__slug=course_slug, slug=cohort_slug).first()
    if cohort is None:
        raise APIError(404, "unknown_cohort", "Cohort was not found.")
    return cohort


def _serialize_enrollment(enrollment) -> dict:
    return {
        "id": enrollment.id,
        "display_name": enrollment.display_name,
        "display_on_leaderboard": enrollment.display_on_leaderboard,
        "display_public_profile": enrollment.display_public_profile,
        "total_score": enrollment.total_score,
        "position_on_leaderboard": enrollment.position_on_leaderboard,
    }


@route(
    "GET",
    "courses/<slug:course_slug>/cohorts/<slug:cohort_slug>/leaderboard",
    "coursework.read",
    "Read the cached leaderboard rows for one cohort",
    LEADERBOARD_RESPONSE,
)
def cohort_leaderboard(request, course_slug, cohort_slug):
    cohort = _cohort(course_slug, cohort_slug)
    current_student = leaderboard.current_student_leaderboard_enrollment(cohort, request.user)
    rows = leaderboard.get_leaderboard_data(cohort, current_student)
    try:
        page = max(int(request.GET.get("page", 1)), 1)
    except ValueError:
        page = 1
    start = (page - 1) * leaderboard.LEADERBOARD_PAGE_SIZE
    end = start + leaderboard.LEADERBOARD_PAGE_SIZE
    return json_response(
        {
            "leaderboard": rows[start:end],
            "page": page,
            "page_size": leaderboard.LEADERBOARD_PAGE_SIZE,
            "count": len(rows),
        }
    )


@route(
    "POST",
    "courses/<slug:course_slug>/cohorts/<slug:cohort_slug>/enrollment-preferences",
    None,
    "Toggle one leaderboard display preference for the signed-in learner",
    PREFERENCE_RESPONSE,
    request=PREFERENCE_REQUEST,
    authentication="session",
)
def update_enrollment_preferences(request, course_slug, cohort_slug):
    data = read_json_object(request)
    field = data.get("field")
    value = data.get("value")
    if not isinstance(field, str) or not isinstance(value, str):
        raise APIError(422, "invalid_body", 'Body must be {"field": str, "value": str}.')
    cohort = _cohort(course_slug, cohort_slug)
    try:
        enrollment, enabled, changed = leaderboard.set_enrollment_preference(
            cohort, request.user, field, value
        )
    except ValueError as error:
        raise APIError(422, "unknown_preference_field", str(error)) from error
    except Enrollment.DoesNotExist as error:
        raise APIError(404, "not_enrolled", "The learner has no active enrollment.") from error
    return json_response(
        {
            "enrollment": _serialize_enrollment(enrollment),
            "field": field,
            "enabled": enabled,
            "changed": changed,
        }
    )
