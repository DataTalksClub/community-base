from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models


class Comment(models.Model):
    class ModerationState(models.TextChoices):
        VISIBLE = "visible", "Visible"
        HIDDEN = "hidden", "Hidden"

    content_id = models.UUIDField(db_index=True)
    target_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    target_object_id = models.CharField(max_length=128, blank=True, default="")
    target = GenericForeignKey("target_content_type", "target_object_id")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="replies",
    )
    body = models.TextField()
    moderation_state = models.CharField(
        max_length=16,
        choices=ModerationState.choices,
        default=ModerationState.VISIBLE,
    )
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moderated_comments",
    )
    moderated_at = models.DateTimeField(null=True, blank=True)
    moderation_reason = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        kind = "Reply" if self.parent_id else "Question"
        return f"{kind} by {self.user_id} on {self.content_id}"

    def clean(self):
        if self.parent_id:
            if self.parent.parent_id is not None:
                raise ValidationError("Replies to replies are not allowed")
            if self.parent.content_id != self.content_id:
                raise ValidationError("A reply must belong to its parent thread")


class CommentVote(models.Model):
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="comment_votes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = (
            models.UniqueConstraint(fields=("comment", "user"), name="comments_vote_unique"),
        )

    def __str__(self):
        return f"Vote by {self.user_id} on comment {self.comment_id}"

    def clean(self):
        if self.comment_id and self.comment.parent_id is not None:
            raise ValidationError("Replies cannot receive votes")
