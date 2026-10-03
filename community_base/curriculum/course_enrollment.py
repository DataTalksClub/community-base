from django.conf import settings
from django.db import models
from django.db.models import Q

from community_base.curriculum.enrollment_sources import ENROLLMENT_SOURCES, SOURCE_MANUAL


class CourseEnrollment(models.Model):
    """An explicit user-course enrollment with soft history."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="curriculum_course_enrollments",
    )
    course = models.ForeignKey(
        "cb_curriculum.Course",
        on_delete=models.CASCADE,
        related_name="course_enrollments",
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)
    unenrolled_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(
        max_length=20,
        choices=ENROLLMENT_SOURCES,
        default=SOURCE_MANUAL,
    )

    class Meta:
        ordering = ("-enrolled_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("user", "course"),
                condition=Q(unenrolled_at__isnull=True),
                name="cb_course_enroll_active_uq",
            ),
        ]

    def __str__(self):
        state = "active"
        if self.unenrolled_at:
            state = "unenrolled"
        return f"{self.user} -> {self.course.title} ({state})"

    @property
    def is_active(self):
        return self.unenrolled_at is None
