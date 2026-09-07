"""Staff API endpoints for curriculum enrollments, certificates and instructors.

Endpoint contracts follow AISL's ``api/views/course_enrollments.py``,
``course_certificates.py`` and ``course_instructors.py``, adapted to the
shared model: enrollments hang off cohorts, so course-level operations target
the course's self-paced cohort unless a cohort slug is given.
"""

from django.core.validators import URLValidator
from django.db import transaction

from community_base.api import route
from community_base.api.errors import APIError
from community_base.api.registry import json_response
from community_base.api.safety import read_json_object
from community_base.curriculum.models import (
    Certificate,
    Cohort,
    Course,
    CourseInstructor,
    Enrollment,
)
from community_base.curriculum.services import ensure_enrollment, unenroll
from community_base.events.models import Host

OBJECT = {"type": "object"}
COLLECTION = {"type": "object", "properties": {"results": {"type": "array"}}}

_url_validator = URLValidator(schemes=["http", "https"])

CERTIFICATE_DELETE_NOT_AVAILABLE_MESSAGE = (
    "Course certificate deletion is not available through the API. "
    "Revoke the certificate in Studio instead."
)


def _course(slug):
    course = Course.objects.filter(slug=slug).first()
    if course is None:
        raise APIError(404, "unknown_course", "Course was not found.")
    return course


def _self_paced_cohort(course) -> Cohort:
    cohort = course.cohorts.filter(mode="self_paced").first()
    if cohort is None:
        cohort = Cohort.objects.create(
            course=course,
            slug="self-paced",
            title=f"{course.title} (self-paced)",
            mode="self_paced",
            curriculum_format="modules",
        )
    return cohort


def _resolve_cohort(course, cohort_slug: str | None) -> Cohort:
    if not cohort_slug:
        return _self_paced_cohort(course)
    cohort = course.cohorts.filter(slug=cohort_slug).first()
    if cohort is None:
        raise APIError(404, "unknown_cohort", "Cohort was not found.")
    return cohort


def _iso(value):
    return value.isoformat() if value is not None else None


def _normalize_emails(raw) -> list[str]:
    seen = set()
    emails = []
    for value in raw:
        if not isinstance(value, str):
            continue
        email = value.strip().lower()
        if email and email not in seen:
            seen.add(email)
            emails.append(email)
    return emails


def _serialize_enrollment(enrollment) -> dict:
    return {
        "user_email": enrollment.user.email,
        "cohort_slug": enrollment.cohort.slug,
        "enrolled_at": _iso(enrollment.enrolled_at),
        "unenrolled_at": _iso(enrollment.unenrolled_at),
        "source": enrollment.source,
    }


@route(
    "GET",
    "courses/<slug:slug>/enrollments",
    "curriculum.read",
    "List course enrollments",
    COLLECTION,
)
def list_enrollments(request, slug):
    course = _course(slug)
    rows = Enrollment.objects.filter(cohort__course=course).select_related("user", "cohort")
    if request.GET.get("include_unenrolled") != "1":
        rows = rows.filter(unenrolled_at__isnull=True)
    return json_response(
        {"enrollments": [_serialize_enrollment(row) for row in rows.order_by("-enrolled_at")]}
    )


@route(
    "POST",
    "courses/<slug:slug>/enrollments",
    "curriculum.write",
    "Bulk enroll learners into the course's self-paced cohort",
    OBJECT,
    request={"type": "object"},
)
def bulk_enroll(request, slug):
    from django.contrib.auth import get_user_model

    data = read_json_object(request)
    single = data.get("user_email")
    many = data.get("user_emails")
    if single is None and many is None:
        raise APIError(422, "missing_field", "Provide user_email or user_emails.")
    combined = [single] if isinstance(single, str) else []
    if isinstance(many, list):
        combined.extend(many)
    emails = _normalize_emails(combined)

    course = _course(slug)
    cohort = _self_paced_cohort(course)
    enrolled, already, without_access, unknown = [], [], [], []
    with transaction.atomic():
        users = {
            user.email.lower(): user for user in get_user_model().objects.filter(email__in=emails)
        }
        for email in emails:
            user = users.get(email)
            if user is None:
                unknown.append(email)
                continue
            _, created = ensure_enrollment(user, cohort, source="admin")
            (enrolled if created else already).append(email)
            from community_base.curriculum.access import can_access

            if not can_access(user, course):
                without_access.append(email)
    return json_response(
        {
            "enrolled": len(enrolled),
            "already_enrolled": len(already),
            "without_access": without_access,
            "unknown_emails": unknown,
        }
    )


@route(
    "DELETE",
    "courses/<slug:slug>/enrollments/<str:email>",
    "curriculum.write",
    "Unenroll a learner from every cohort of the course",
    OBJECT,
)
def delete_enrollment(request, slug, email):
    from django.contrib.auth import get_user_model

    course = _course(slug)
    user = get_user_model().objects.filter(email__iexact=email.strip().lower()).first()
    if user is not None:
        for cohort in course.cohorts.all():
            unenroll(user, cohort)
    return json_response({"unenrolled": True})


@route(
    "GET",
    "courses/<slug:slug>/certificates",
    "curriculum.read",
    "List course certificates",
    COLLECTION,
)
def list_certificates(request, slug):
    course = _course(slug)
    rows = Certificate.objects.filter(enrollment__cohort__course=course).select_related(
        "enrollment__user"
    )
    return json_response(
        {
            "certificates": [
                {
                    "id": str(row.pk),
                    "user_email": row.enrollment.user.email,
                    "cohort_slug": row.enrollment.cohort.slug,
                    "url": row.url,
                    "issued_at": _iso(row.issued_at),
                }
                for row in rows
            ]
        }
    )


@route(
    "POST",
    "courses/<slug:slug>/certificates",
    "curriculum.write",
    "Issue or update a certificate for one learner",
    OBJECT,
    request={"type": "object"},
)
def issue_certificate(request, slug):
    from django.contrib.auth import get_user_model

    data = read_json_object(request)
    email = str(data.get("user_email") or "").strip().lower()
    if not email:
        raise APIError(422, "missing_field", "user_email is required.")
    course = _course(slug)
    cohort = _resolve_cohort(course, data.get("cohort_slug"))
    user = get_user_model().objects.filter(email__iexact=email).first()
    if user is None:
        raise APIError(422, "unknown_email", "No account matches user_email.")
    enrollment = Enrollment.objects.filter(
        user=user, cohort=cohort, unenrolled_at__isnull=True
    ).first()
    if enrollment is None:
        raise APIError(422, "not_enrolled", "The learner has no active enrollment.")

    url = str(data.get("url") or "")
    if url:
        try:
            _url_validator(url)
        except Exception as error:
            raise APIError(422, "invalid_url", "Certificate url must be http(s).") from error
    certificate, _created = Certificate.objects.get_or_create(enrollment=enrollment)
    certificate.url = url
    certificate.save(update_fields=["url"])
    return json_response(
        {
            "id": str(certificate.pk),
            "user_email": email,
            "cohort_slug": cohort.slug,
            "url": certificate.url,
            "issued_at": _iso(certificate.issued_at),
        }
    )


@route(
    "DELETE",
    "courses/<slug:slug>/certificates/<str:email>",
    "curriculum.write",
    "Certificate deletion is not available",
    OBJECT,
)
def delete_certificate(request, slug, email):
    raise APIError(
        405,
        "curriculum_certificate_delete_not_available",
        CERTIFICATE_DELETE_NOT_AVAILABLE_MESSAGE,
    )


def _serialize_instructors(course) -> dict:
    return {
        "instructors": [
            {"slug": link.host.slug, "name": link.host.name, "position": link.position}
            for link in CourseInstructor.objects.filter(course=course).order_by("position", "pk")
        ]
    }


@route(
    "GET",
    "courses/<slug:slug>/instructors",
    "curriculum.read",
    "List ordered course instructors",
    OBJECT,
)
def list_instructors(request, slug):
    course = _course(slug)
    return json_response(_serialize_instructors(course))


@route(
    "PUT",
    "courses/<slug:slug>/instructors",
    "curriculum.write",
    "Replace ordered course instructors",
    OBJECT,
    request={"type": "object"},
)
def replace_instructors(request, slug):
    data = read_json_object(request)
    if set(data) != {"instructor_ids"} or not isinstance(data["instructor_ids"], list):
        raise APIError(422, "invalid_body", 'Body must be {"instructor_ids": [...]}.')
    course = _course(slug)
    if course.source_content_id:
        raise APIError(409, "source_owned", "Course instructors are source-owned.")
    identifiers = data["instructor_ids"]
    if not all(isinstance(item, str) for item in identifiers):
        raise APIError(422, "invalid_ids", "instructor_ids must be strings.")
    if len(set(identifiers)) != len(identifiers):
        raise APIError(422, "duplicate_ids", "instructor_ids must be unique.")
    hosts = []
    for identifier in identifiers:
        host = Host.objects.filter(slug=identifier, kind="instructor").first()
        if host is None:
            raise APIError(422, "unknown_instructor", f"No instructor matches {identifier!r}.")
        hosts.append(host)
    with transaction.atomic():
        CourseInstructor.objects.filter(course=course).delete()
        for position, host in enumerate(hosts):
            CourseInstructor.objects.create(course=course, host=host, position=position)
    return json_response(_serialize_instructors(course))
