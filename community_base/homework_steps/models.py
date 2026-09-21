import uuid

from django.conf import settings
from django.db import models


class HomeworkDraft(models.Model):
    """Only in-progress input; never a submission or scoring record."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    assignment_key = models.CharField(max_length=255)
    answers = models.JSONField(default=dict)
    final_fields = models.JSONField(default=dict)
    token = models.UUIDField(default=uuid.uuid4, editable=False)
    revision = models.PositiveIntegerField(default=0)
    saved_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "assignment_key"), name="cb_homework_draft_identity_uq"
            )
        ]

    def __str__(self):
        return f"Draft {self.pk} for {self.assignment_key}"
