"""Member APIs for the coursework learner flows.

The donor's learner surface is entirely server-rendered and its JSON API is
staff-oriented, so per the donor analysis these member endpoints follow the
registry-route shape adopted in C5.1c instead of a donor endpoint.
"""

from community_base.api import route
from community_base.api.errors import APIError
from community_base.api.registry import json_response
from community_base.api.safety import read_json_object
from community_base.coursework.leaderboard import (
    LEADERBOARD_PAGE_SIZE,
    current_student_leaderboard_enrollment,
    get_leaderboard_data,
    set_enrollment_preference,
)
from community_base.curriculum.models import Cohort, Enrollment

OBJECT_SCHEMA = {"type": "object"}
PREFERENCE_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["enrollment", "field", "enabled", "changed"],
    "properties": {
        "enrollment": OBJECT_SCHEMA,
        "field": {"type": "string"},
        "enabled": {"type": "boolean"},
        "changed": {"type": "boolean"},
    },
}
LEADERBOARD_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["leaderboard", "page", "page_size", "count"],
    "properties": {
        "leaderboard": {"type": "array", "items": OBJECT_SCHEMA},
        "page": {"type": "integer"},
        "page_size": {"type": "integer"},
        "count": {"type": "integer"},
    },
}


def _cohort_for(course_slug, cohort_slug) -> Cohort:
    cohort = Cohort.objects.filter(course__slug=course_slug, slug=cohort_slug).first()
    if cohort is None:
        raise APIError(404, "unknown_cohort", "Cohort was not found.")
    return cohort


@route(
    "POST",
    "courses/<slug:course_slug>/cohorts/<slug:cohort_slug>/enrollment-preferences",
    None,
    "Toggle one leaderboard display preference for the signed-in learner",
    PREFERENCE_RESPONSE_SCHEMA,
    request={
        "type": "object",
        "required": ["field", "value"],
        "properties": {"field": {"type": "string"}, "value": {"type": "string"}},
    },
    authentication="session",
)
def update_enrollment_preference(request, course_slug, cohort_slug):
    cohort = _cohort_for(course_slug, cohort_slug)
    data = read_json_object(request)
    field = data.get("field")
    value = data.get("value")
    if not isinstance(field, str) or not isinstance(value, str):
        raise APIError(400, "invalid_body", "Provide string fields 'field' and 'value'.")
    try:
        enrollment, enabled, changed = set_enrollment_preference(cohort, request.user, field, value)
    except ValueError as error:
        raise APIError(400, "unknown_field", str(error)) from error
    except Enrollment.DoesNotExist as error:
        raise APIError(404, "not_enrolled", "No active enrollment in this cohort.") from error
    return json_response(
        {
            "enrollment": {"id": enrollment.id},
            "field": field,
            "enabled": enabled,
            "changed": changed,
        }
    )


@route(
    "GET",
    "courses/<slug:course_slug>/cohorts/<slug:cohort_slug>/leaderboard",
    None,
    "Read the leaderboard rows for one cohort",
    LEADERBOARD_RESPONSE_SCHEMA,
    authentication="session",
)
def get_cohort_leaderboard(request, course_slug, cohort_slug):
    cohort = _cohort_for(course_slug, cohort_slug)
    current_student = current_student_leaderboard_enrollment(cohort, request.user)
    enrollments_data = get_leaderboard_data(cohort, current_student)
    try:
        page = max(1, int(request.GET.get("page", "1")))
    except ValueError:
        page = 1
    start = (page - 1) * LEADERBOARD_PAGE_SIZE
    return json_response(
        {
            "leaderboard": enrollments_data[start : start + LEADERBOARD_PAGE_SIZE],
            "page": page,
            "page_size": LEADERBOARD_PAGE_SIZE,
            "count": len(enrollments_data),
        }
    )
