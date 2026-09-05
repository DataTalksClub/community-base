from django.db import models

from community_base.content_sync.models import ContentSource


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
