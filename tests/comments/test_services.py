import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from community_base.comments.models import Comment, CommentVote
from community_base.comments.registry import (
    register_comment_target,
    registered_comment_targets,
    resolve_comment_target,
)
from community_base.comments.services import (
    can_read_thread,
    can_write_thread,
    create_comment,
    delete_thread,
    moderate_comment,
    toggle_comment_vote,
)
from community_base.comments.signals import comment_created
from community_base.content_sync.models import ContentSource
from community_base.notifications.models import Notification

pytestmark = pytest.mark.django_db(transaction=True)


def account(email="member@example.com", **kwargs):
    return get_user_model().objects.create_user(email=email, **kwargs)


def source(slug="fixture"):
    return ContentSource.objects.create(slug=slug, repo_name=f"owner/{slug}")


def test_registered_target_resolves_and_populates_generic_relation():
    target = source()
    registration = register_comment_target("fixture", ContentSource, content_id_field="id")
    user = account()

    comment = create_comment(content_id=target.pk, user=user, body=" A question ")

    assert registered_comment_targets() == (registration,)
    assert resolve_comment_target(target.pk).target == target
    assert comment.body == "A question"
    assert comment.target == target
    assert comment.target_object_id == str(target.pk)


def test_target_registration_is_idempotent_and_rejects_conflicts():
    first = register_comment_target("fixture", ContentSource, content_id_field="id")
    second = register_comment_target("fixture", ContentSource, content_id_field="id")

    assert first == second
    with pytest.raises(ValueError, match="already registered"):
        register_comment_target("fixture", ContentSource, content_id_field="slug")
    with pytest.raises(ValueError, match="invalid"):
        register_comment_target("Secret Target", ContentSource, content_id_field="id")


def test_registered_read_and_write_policies_are_applied():
    target = source()
    owner = account("owner@example.com")
    other = account("other@example.com")
    register_comment_target(
        "private",
        ContentSource,
        content_id_field="id",
        can_read=lambda target, user: user == owner,
        can_write=lambda target, user: user == owner,
    )

    assert can_read_thread(target.pk, owner) is True
    assert can_read_thread(target.pk, other) is False
    assert can_write_thread(target.pk, other) is False
    with pytest.raises(PermissionError):
        create_comment(content_id=target.pk, user=other, body="Denied")


def test_unregistered_thread_is_public_read_and_authenticated_write():
    content_id = uuid.uuid4()
    anonymous = type("Anonymous", (), {"is_authenticated": False})()
    user = account()

    assert can_read_thread(content_id, anonymous) is True
    assert can_write_thread(content_id, anonymous) is False
    assert can_write_thread(content_id, user) is True


def test_reply_depth_and_thread_must_match():
    user = account()
    first_thread = uuid.uuid4()
    parent = create_comment(content_id=first_thread, user=user, body="Parent")
    reply = create_comment(content_id=first_thread, user=user, body="Reply", parent=parent)

    with pytest.raises(ValueError, match="parent"):
        create_comment(content_id=first_thread, user=user, body="Nested", parent=reply)
    with pytest.raises(ValueError, match="parent"):
        create_comment(content_id=uuid.uuid4(), user=user, body="Wrong", parent=parent)

    invalid = Comment(content_id=first_thread, user=user, body="Nested", parent=reply)
    with pytest.raises(ValidationError, match="Replies to replies"):
        invalid.full_clean()


def test_comment_body_is_required_and_bounded(settings):
    settings.COMMUNITY_BASE = {"COMMENTS_MAX_BODY_LENGTH": 5}
    user = account()

    with pytest.raises(ValueError, match="required"):
        create_comment(content_id=uuid.uuid4(), user=user, body=" ")
    with pytest.raises(ValueError, match="too long"):
        create_comment(content_id=uuid.uuid4(), user=user, body="123456")


def test_vote_toggle_is_unique_and_replies_cannot_receive_votes():
    user = account()
    other = account("other@example.com")
    content_id = uuid.uuid4()
    comment = create_comment(content_id=content_id, user=user, body="Question")

    assert toggle_comment_vote(comment=comment, user=other) == (True, 1)
    assert toggle_comment_vote(comment=comment, user=other) == (False, 0)
    reply = create_comment(content_id=content_id, user=other, body="Reply", parent=comment)
    with pytest.raises(ValueError, match="replies"):
        toggle_comment_vote(comment=reply, user=user)


def test_only_staff_can_moderate_comment():
    user = account()
    staff = account("staff@example.com", is_staff=True)
    comment = create_comment(content_id=uuid.uuid4(), user=user, body="Question")

    with pytest.raises(PermissionError, match="staff"):
        moderate_comment(comment, moderator=user, hidden=True)
    moderate_comment(comment, moderator=staff, hidden=True, reason="review")
    comment.refresh_from_db()
    assert comment.moderation_state == Comment.ModerationState.HIDDEN
    assert comment.moderated_by == staff
    assert comment.moderation_reason == "review"


def test_cascade_target_delete_removes_thread_votes_and_exact_notifications():
    target = source()
    user = account()
    register_comment_target(
        "fixture",
        ContentSource,
        content_id_field="id",
        cascade_delete=True,
    )
    comment = create_comment(content_id=target.pk, user=user, body="Question")
    CommentVote.objects.create(comment=comment, user=user)
    exact = Notification.objects.create(user=user, title="Comment", thread_content_id=target.pk)
    other = Notification.objects.create(user=user, title="Other", thread_content_id=uuid.uuid4())

    target.delete()

    assert not Comment.objects.exists()
    assert not CommentVote.objects.exists()
    assert not Notification.objects.filter(pk=exact.pk).exists()
    assert Notification.objects.filter(pk=other.pk).exists()


def test_delete_thread_returns_counts():
    user = account()
    content_id = uuid.uuid4()
    comment = create_comment(content_id=content_id, user=user, body="Question")
    CommentVote.objects.create(comment=comment, user=user)

    assert delete_thread(content_id) == {
        "comments": 1,
        "comment_votes": 1,
        "notifications": 0,
    }


def test_created_signal_is_emitted_after_commit():
    received = []

    def receiver(sender, **kwargs):
        received.append(kwargs["comment"].pk)

    comment_created.connect(receiver, weak=False)
    try:
        comment = create_comment(content_id=uuid.uuid4(), user=account(), body="Question")
    finally:
        comment_created.disconnect(receiver)

    assert received == [comment.pk]
