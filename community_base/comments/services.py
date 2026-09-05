from django.db import transaction
from django.utils import timezone

from community_base.comments.models import Comment, CommentVote
from community_base.comments.registry import resolve_comment_target
from community_base.kernel import conf


def can_read_thread(content_id, user):
    resolved = resolve_comment_target(content_id)
    if resolved is None:
        return True
    return bool(resolved.registration.can_read(resolved.target, user))


def can_write_thread(content_id, user):
    resolved = resolve_comment_target(content_id)
    if resolved is None:
        return bool(getattr(user, "is_authenticated", False))
    return bool(resolved.registration.can_write(resolved.target, user))


def _body(value):
    body = str(value or "").strip()
    try:
        maximum = max(1, int(conf.get("COMMENTS_MAX_BODY_LENGTH")))
    except (TypeError, ValueError):
        maximum = 10_000
    if not body:
        raise ValueError("comment body is required")
    if len(body) > maximum:
        raise ValueError("comment body is too long")
    return body


@transaction.atomic
def create_comment(*, content_id, user, body, parent=None):
    if not can_write_thread(content_id, user):
        raise PermissionError("comment thread is not writable")
    if parent is not None and (parent.parent_id or parent.content_id != content_id):
        raise ValueError("invalid comment parent")
    resolved = resolve_comment_target(content_id)
    values = {}
    if resolved is not None:
        values = {
            "target_content_type": resolved.content_type,
            "target_object_id": str(resolved.target.pk),
        }
    comment = Comment(
        content_id=content_id,
        user=user,
        body=_body(body),
        parent=parent,
        **values,
    )
    comment.full_clean()
    comment.save()
    from community_base.comments.signals import comment_created

    transaction.on_commit(
        lambda: comment_created.send(
            sender=Comment,
            comment=comment,
            content_id=content_id,
        )
    )
    return comment


@transaction.atomic
def toggle_comment_vote(*, comment, user):
    if comment.parent_id:
        raise ValueError("replies cannot receive votes")
    if not can_write_thread(comment.content_id, user):
        raise PermissionError("comment thread is not writable")
    vote, created = CommentVote.objects.get_or_create(comment=comment, user=user)
    if not created:
        vote.delete()
    return created, CommentVote.objects.filter(comment=comment).count()


@transaction.atomic
def moderate_comment(comment, *, moderator, hidden, reason=""):
    if not getattr(moderator, "is_staff", False):
        raise PermissionError("comment moderation requires staff")
    comment.moderation_state = (
        Comment.ModerationState.HIDDEN if hidden else Comment.ModerationState.VISIBLE
    )
    comment.moderated_by = moderator
    comment.moderated_at = timezone.now()
    comment.moderation_reason = str(reason or "")[:200]
    comment.save(
        update_fields=(
            "moderation_state",
            "moderated_by",
            "moderated_at",
            "moderation_reason",
            "updated_at",
        )
    )
    return comment


@transaction.atomic
def delete_thread(content_id):
    comments = Comment.objects.filter(content_id=content_id)
    counts = {
        "comments": comments.count(),
        "comment_votes": CommentVote.objects.filter(comment__content_id=content_id).count(),
    }
    notifications = None
    try:
        from community_base.notifications.models import Notification

        notifications = Notification.objects.filter(thread_content_id=content_id)
        counts["notifications"] = notifications.count()
        notifications.delete()
    except (ImportError, RuntimeError):
        counts["notifications"] = 0
    comments.delete()
    return counts
