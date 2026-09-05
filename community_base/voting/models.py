import uuid

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from community_base.kernel.access import LEVEL_MAIN, LEVEL_PREMIUM
from community_base.kernel.conf import get

POLL_TYPE_CHOICES = (("topic", "Topic"), ("course", "Mini-course"))
POLL_STATUS_CHOICES = (("open", "Open"), ("closed", "Closed"))


class Poll(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True, default="")
    poll_type = models.CharField(max_length=20, choices=POLL_TYPE_CHOICES, default="topic")
    required_level = models.IntegerField(default=LEVEL_MAIN)
    status = models.CharField(max_length=20, choices=POLL_STATUS_CHOICES, default="open")
    allow_proposals = models.BooleanField(default=False)
    max_votes_per_user = models.PositiveIntegerField(default=3)
    closes_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        levels = get("VOTING_POLL_LEVELS")
        if not isinstance(levels, dict):
            raise TypeError("VOTING_POLL_LEVELS must be a dictionary")
        self.required_level = int(
            levels.get(
                self.poll_type,
                {"topic": LEVEL_MAIN, "course": LEVEL_PREMIUM}.get(
                    self.poll_type, self.required_level
                ),
            )
        )
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("poll_detail", kwargs={"poll_id": self.pk})

    @property
    def is_closed(self):
        return self.status == "closed" or bool(self.closes_at and timezone.now() >= self.closes_at)

    @property
    def total_votes(self):
        return self.votes.count()

    @property
    def options_count(self):
        return self.options.count()


class PollOption(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="options")
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True, default="")
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposed_options",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self):
        return self.title

    @property
    def vote_count(self):
        return self.votes.count()


class PollVote(models.Model):
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="votes")
    option = models.ForeignKey(PollOption, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="poll_votes"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = (
            models.UniqueConstraint(
                fields=("poll", "user", "option"), name="voting_unique_poll_user_option"
            ),
        )

    def __str__(self):
        return f"{self.user} -> {self.option}"
