from django.conf import settings
from django.db import models


class MemberNoteQuerySet(models.QuerySet):
    def internal(self):
        return self.filter(visibility=MemberNote.Visibility.INTERNAL)

    def external(self):
        return self.filter(visibility=MemberNote.Visibility.EXTERNAL)

    def visible_to(self, user):
        if not getattr(user, "is_authenticated", False):
            return self.none()
        if getattr(user, "is_staff", False):
            return self
        return self.external().filter(member=user)


class MemberNote(models.Model):
    class Visibility(models.TextChoices):
        INTERNAL = "internal", "Internal"
        EXTERNAL = "external", "External"

    class Kind(models.TextChoices):
        GENERAL = "general", "General"
        INTAKE = "intake", "Intake"
        SUPPORT = "support", "Support"
        OUTREACH = "outreach", "Outreach"

    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="community_base_member_notes",
    )
    visibility = models.CharField(
        max_length=10, choices=Visibility.choices, default=Visibility.INTERNAL
    )
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.GENERAL)
    body = models.TextField()
    tags = models.JSONField(default=list, blank=True)
    source_type = models.CharField(max_length=40, blank=True, default="", db_index=True)
    source_metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="community_base_authored_member_notes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = MemberNoteQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at", "-pk")

    def __str__(self):
        return f"Member note {self.pk} for user {self.member_id}"
