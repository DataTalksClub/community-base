from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from community_base.curriculum.enrollment_sources import SOURCE_MANUAL
from community_base.curriculum.models import Course, CourseEnrollment


def _is_authenticated(user) -> bool:
    return user is not None and getattr(user, "is_authenticated", False)


def get_active_course_enrollment(user, course: Course) -> CourseEnrollment | None:
    if not _is_authenticated(user):
        return None
    return CourseEnrollment.objects.filter(
        user=user,
        course=course,
        unenrolled_at__isnull=True,
    ).first()


def is_course_enrolled(user, course: Course) -> bool:
    return get_active_course_enrollment(user, course) is not None


def ensure_course_enrollment(
    user, course: Course, source: str = SOURCE_MANUAL
) -> tuple[CourseEnrollment | None, bool]:
    if not _is_authenticated(user):
        return None, False
    with transaction.atomic():
        return CourseEnrollment.objects.get_or_create(
            user=user,
            course=course,
            unenrolled_at=None,
            defaults={"source": source},
        )


def unenroll_from_course(user, course: Course) -> bool:
    if not _is_authenticated(user):
        return False
    with transaction.atomic():
        updated = CourseEnrollment.objects.filter(
            user=user,
            course=course,
            unenrolled_at__isnull=True,
        ).update(unenrolled_at=timezone.now())
    return bool(updated)


def course_enrollment_history(user, *, course: Course | None = None) -> QuerySet[CourseEnrollment]:
    if not _is_authenticated(user):
        return CourseEnrollment.objects.none()
    history = CourseEnrollment.objects.filter(user=user)
    if course is not None:
        history = history.filter(course=course)
    return history


def active_course_enrollment_count(course: Course) -> int:
    return CourseEnrollment.objects.filter(
        course=course,
        unenrolled_at__isnull=True,
    ).count()
