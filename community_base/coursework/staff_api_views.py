"""Staff peer-review state and assignment endpoints for a course.

- ``GET /api/v1/courses/<slug>/peer-reviews`` -- read peer-review state,
  submission counts, assignment counts, completed reviews, and deadline for
  the course's projects (optionally filtered by ``cohort`` and/or ``project``).
- ``POST /api/v1/courses/<slug>/peer-reviews/assignments`` -- create round-robin
  peer review assignments (moves eligible dated projects to ``Peer reviewing``,
  sends ``coursework.review_assigned`` emails, and is idempotent).
- ``GET``/``POST /api/v1/courses/<slug>/cohorts/<cohort>/homeworks/<homework>/state`` and
  ``POST .../close`` -- read, set or close a homework's state (``homework_state``), CMP's
  token-authenticated homework ``PATCH`` with ``state`` carried onto scoped bearer routes.
"""

from django.db.models import Count, Q

from community_base.api import route
from community_base.api.errors import APIError
from community_base.api.registry import json_response
from community_base.api.safety import read_json_object
from community_base.coursework.homework_state import (
    VALID_HOMEWORK_STATES,
    InvalidHomeworkState,
    close_homework,
    set_homework_state,
)
from community_base.coursework.models import (
    Homework,
    HomeworkState,
    PeerReview,
    PeerReviewState,
    Project,
    ProjectState,
    ProjectSubmission,
    SubmissionReviewState,
)
from community_base.coursework.pooling import form_pooled_batches
from community_base.coursework.review import (
    ProjectActionStatus,
    assign_peer_reviews_for_project,
)
from community_base.curriculum.models import Cohort, Course

OBJECT_SCHEMA = {"type": "object"}
PEER_REVIEWS_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["course_id", "course", "course_title", "projects"],
    "properties": {
        "course_id": {"type": "integer"},
        "course": {"type": "string"},
        "course_title": {"type": "string"},
        "projects": {"type": "array", "items": OBJECT_SCHEMA},
    },
}
PEER_REVIEW_ASSIGNMENTS_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["course_id", "course", "batched", "reviews_assigned", "projects"],
    "properties": {
        "course_id": {"type": "integer"},
        "course": {"type": "string"},
        "batched": {"type": "integer"},
        "reviews_assigned": {"type": "integer"},
        "projects": {"type": "array", "items": OBJECT_SCHEMA},
    },
}

_STATUS_KEYS = {
    SubmissionReviewState.AWAITING_ASSIGNMENT.value: "awaiting_assignment",
    SubmissionReviewState.IN_REVIEW.value: "in_review",
    SubmissionReviewState.SCORED.value: "scored",
}


def _isoformat_or_none(value) -> str | None:
    return value.isoformat() if value is not None else None


def _resolve_scope(course: Course, cohort_slug: str, project_slug: str):
    cohort = None
    if cohort_slug:
        cohort = Cohort.objects.filter(course=course, slug=cohort_slug).first()
        if cohort is None:
            raise APIError(404, "unknown_cohort", "Cohort was not found.")
    project = None
    if project_slug:
        qs = Project.objects.filter(cohort__course=course, slug=project_slug)
        if cohort is not None:
            qs = qs.filter(cohort=cohort)
        project = qs.select_related("cohort").first()
        if project is None:
            raise APIError(404, "unknown_project", "Project was not found.")
    return cohort, project


def _annotated_projects(course: Course, cohort, project) -> list[Project]:
    qs = Project.objects.filter(cohort__course=course).select_related("cohort")
    if cohort is not None:
        qs = qs.filter(cohort=cohort)
    if project is not None:
        qs = qs.filter(pk=project.pk)
    real = Q(submissions__volunteer_review_only=False)
    annotations = {
        "submissions_count": Count("submissions", filter=real, distinct=True),
        "assignments_count": Count(
            "submissions__reviews_under_evaluation", filter=real, distinct=True
        ),
        "completed_reviews_count": Count(
            "submissions__reviews_under_evaluation",
            filter=real
            & Q(submissions__reviews_under_evaluation__state=PeerReviewState.SUBMITTED.value),
            distinct=True,
        ),
    }
    for code, key in _STATUS_KEYS.items():
        annotations[f"status_{key}"] = Count(
            "submissions",
            filter=real & Q(submissions__review_state=code),
            distinct=True,
        )
    return list(qs.annotate(**annotations).order_by("submission_due_date", "pk"))


def _serialize_cohort_ref(cohort: Cohort) -> dict:
    return {
        "id": cohort.pk,
        "slug": cohort.slug,
        "title": cohort.title,
        "mode": cohort.mode,
    }


def _serialize_project(project: Project) -> dict:
    assignments = project.assignments_count
    completed = project.completed_reviews_count
    by_status = {key: getattr(project, f"status_{key}", 0) for key in _STATUS_KEYS.values()}
    review_due = _isoformat_or_none(project.peer_review_due_date)
    return {
        "id": project.pk,
        "slug": project.slug,
        "title": project.title,
        "cohort": _serialize_cohort_ref(project.cohort),
        "state": project.state,
        "state_label": project.get_state_display(),
        "submission_due_at": _isoformat_or_none(project.submission_due_date),
        "review_due_at": review_due,
        "deadline": review_due,
        "peer_review_count": project.number_of_peers_to_evaluate,
        "submissions_count": project.submissions_count,
        "submissions_by_status": by_status,
        "assignments_count": assignments,
        "completed_reviews_count": completed,
        "pending_reviews_count": max(0, assignments - completed),
    }


def _parse_optional_body(request) -> dict:
    if not request.body or not request.body.strip():
        return {}
    return read_json_object(request)


def _run_assignment(course: Course, cohort, project) -> tuple[int, int]:
    qs = Project.objects.filter(cohort__course=course).select_related("cohort")
    if cohort is not None:
        qs = qs.filter(cohort=cohort)
    if project is not None:
        qs = qs.filter(pk=project.pk)

    batched = 0
    reviews_assigned = 0
    for item in qs.order_by("submission_due_date", "pk"):
        if item.uses_pooled_review:
            batches = form_pooled_batches(item)
            if batches:
                batch_ids = [b.pk for b in batches]
                reviews_count = PeerReview.objects.filter(batch_id__in=batch_ids).count()
                sub_count = (
                    ProjectSubmission.objects.filter(
                        reviews_under_evaluation__batch_id__in=batch_ids
                    )
                    .distinct()
                    .count()
                )
                batched += sub_count
                reviews_assigned += reviews_count
            continue
        if item.state != ProjectState.COLLECTING_SUBMISSIONS.value:
            continue
        status, _message = assign_peer_reviews_for_project(item)
        if status == ProjectActionStatus.OK:
            batched += ProjectSubmission.objects.filter(
                project=item, volunteer_review_only=False
            ).count()
            reviews_assigned += PeerReview.objects.filter(
                submission_under_evaluation__project=item, optional=False
            ).count()
    return batched, reviews_assigned


@route(
    "GET",
    "courses/<slug:slug>/peer-reviews",
    "coursework.read",
    "Read peer-review state, counts, and deadlines for a course",
    PEER_REVIEWS_RESPONSE_SCHEMA,
)
def course_peer_reviews(request, slug):
    """``GET /api/v1/courses/<slug>/peer-reviews``."""
    course = Course.objects.filter(slug=slug).first()
    if course is None:
        raise APIError(404, "unknown_course", "Course was not found.")
    cohort_slug = (request.GET.get("cohort") or "").strip()
    project_slug = (request.GET.get("project") or "").strip()
    cohort, project = _resolve_scope(course, cohort_slug, project_slug)
    projects = _annotated_projects(course, cohort, project)
    return json_response(
        {
            "course_id": course.pk,
            "course": course.slug,
            "course_title": course.title,
            "projects": [_serialize_project(p) for p in projects],
        }
    )


@route(
    "POST",
    "courses/<slug:slug>/peer-reviews/assignments",
    "coursework.write",
    "Create round-robin peer review assignments for a course (idempotent)",
    PEER_REVIEW_ASSIGNMENTS_RESPONSE_SCHEMA,
    request={
        "type": "object",
        "properties": {
            "cohort": {"type": "string"},
            "project": {"type": "string"},
        },
    },
)
def course_peer_review_assignments(request, slug):
    """``POST /api/v1/courses/<slug>/peer-reviews/assignments``."""
    course = Course.objects.filter(slug=slug).first()
    if course is None:
        raise APIError(404, "unknown_course", "Course was not found.")
    body = _parse_optional_body(request)
    cohort_slug = str(body.get("cohort") or "").strip()
    project_slug = str(body.get("project") or "").strip()
    cohort, project = _resolve_scope(course, cohort_slug, project_slug)
    batched, reviews_assigned = _run_assignment(course, cohort, project)
    projects = _annotated_projects(course, cohort, project)
    return json_response(
        {
            "course_id": course.pk,
            "course": course.slug,
            "batched": batched,
            "reviews_assigned": reviews_assigned,
            "projects": [_serialize_project(p) for p in projects],
        }
    )


# --- homework state (intake 52159dbe) ---------------------------------------

HOMEWORK_PATH = (
    "courses/<slug:course_slug>/cohorts/<slug:cohort_slug>/homeworks/<slug:homework_slug>"
)
STATE_SCHEMA = {"type": "string", "enum": list(VALID_HOMEWORK_STATES)}
HOMEWORK_STATE_SCHEMA = {
    "type": "object",
    "required": ["id", "slug", "course_slug", "cohort_slug", "state", "state_name"],
    "properties": {
        "id": {"type": "integer"},
        "slug": {"type": "string"},
        "course_slug": {"type": "string"},
        "cohort_slug": {"type": "string"},
        "state": STATE_SCHEMA,
        "state_name": {"type": "string", "enum": ["closed", "open", "scored"]},
    },
}
READ_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["homework"],
    "properties": {"homework": HOMEWORK_STATE_SCHEMA},
}
CHANGE_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["homework", "previous_state", "changed"],
    "properties": {
        "homework": HOMEWORK_STATE_SCHEMA,
        "previous_state": STATE_SCHEMA,
        "changed": {"type": "boolean"},
    },
}
SET_STATE_REQUEST_SCHEMA = {
    "type": "object",
    "required": ["state"],
    "properties": {
        "state": {
            "type": "string",
            "description": "A state code (CL, OP, SC) or name (closed, open, scored).",
        }
    },
}


def _homework(course_slug, cohort_slug, homework_slug) -> Homework:
    homework = (
        Homework.objects.select_related("cohort__course")
        .filter(
            cohort__course__slug=course_slug,
            cohort__slug=cohort_slug,
            slug=homework_slug,
        )
        .first()
    )
    if homework is None:
        raise APIError(404, "unknown_homework", "Homework was not found.")
    return homework


def serialize_homework_state(homework: Homework) -> dict:
    return {
        "id": homework.pk,
        "slug": homework.slug,
        "course_slug": homework.cohort.course.slug,
        "cohort_slug": homework.cohort.slug,
        "state": homework.state,
        "state_name": HomeworkState(homework.state).name.lower(),
    }


def _change_response(change) -> dict:
    return {
        "homework": serialize_homework_state(change.homework),
        "previous_state": change.previous_state,
        "changed": change.changed,
    }


@route(
    "GET",
    f"{HOMEWORK_PATH}/state",
    "coursework.read",
    "Read a homework's state",
    READ_RESPONSE_SCHEMA,
)
def get_homework_state(request, course_slug, cohort_slug, homework_slug):
    homework = _homework(course_slug, cohort_slug, homework_slug)
    return json_response({"homework": serialize_homework_state(homework)})


@route(
    "POST",
    f"{HOMEWORK_PATH}/state",
    "coursework.write",
    "Set a homework's state (CMP homework state PATCH parity)",
    CHANGE_RESPONSE_SCHEMA,
    request=SET_STATE_REQUEST_SCHEMA,
)
def post_homework_state(request, course_slug, cohort_slug, homework_slug):
    homework = _homework(course_slug, cohort_slug, homework_slug)
    data = read_json_object(request)
    if "state" not in data:
        raise APIError(400, "missing_field", "Provide 'state'.", details={"field": "state"})
    try:
        change = set_homework_state(homework, data["state"])
    except InvalidHomeworkState as error:
        raise APIError(
            400,
            "invalid_homework_state",
            f"Invalid state. Must be one of: {list(VALID_HOMEWORK_STATES)}",
            details={"valid_states": list(VALID_HOMEWORK_STATES)},
        ) from error
    return json_response(_change_response(change))


@route(
    "POST",
    f"{HOMEWORK_PATH}/close",
    "coursework.write",
    "Close a homework to new submissions",
    CHANGE_RESPONSE_SCHEMA,
)
def post_homework_close(request, course_slug, cohort_slug, homework_slug):
    homework = _homework(course_slug, cohort_slug, homework_slug)
    return json_response(_change_response(close_homework(homework)))
