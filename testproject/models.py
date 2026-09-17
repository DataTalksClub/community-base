from django.db import models

from community_base.content_sync.models import ContentSource
from community_base.kernel.models import AppendOnlyManager, RevisionedModel


class FixtureContent(models.Model):
    source = models.ForeignKey(ContentSource, on_delete=models.CASCADE)
    source_key = models.CharField(max_length=200)
    title = models.CharField(max_length=200)
    fingerprint = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("source", "source_key"), name="test_fixture_content_source_key"
            ),
        )

    def __str__(self):
        return self.title


class FixtureRevisionedRecord(RevisionedModel):
    """Exercises the kernel's optimistic concurrency contract in tests."""

    label = models.CharField(max_length=200)

    def __str__(self):
        return self.label


class FixtureAppendOnlyRecord(models.Model):
    """Exercises the kernel's append-only contract in tests."""

    label = models.CharField(max_length=200)

    objects = AppendOnlyManager()

    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"

    def __str__(self):
        return self.label
