import uuid

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from community_base.accounts.services.privacy import build_user_data_export
from community_base.comments.models import CommentVote
from community_base.comments.services import create_comment

pytestmark = pytest.mark.django_db(transaction=True)


def account(email, **kwargs):
    return get_user_model().objects.create_user(email=email, **kwargs)


def test_comments_studio_requires_staff(client):
    client.force_login(account("member@example.com"))

    assert client.get(reverse("comments_studio_list")).status_code == 403


def test_staff_can_search_hide_and_show_comment(client):
    member = account("member@example.com")
    staff = account("staff@example.com", is_staff=True)
    comment = create_comment(content_id=uuid.uuid4(), user=member, body="Review this")
    client.force_login(staff)

    response = client.get(reverse("comments_studio_list"), {"q": "Review"})
    hidden = client.post(
        reverse("comments_studio_moderate", args=(comment.pk,)),
        {"action": "hide", "reason": "needs review"},
    )

    assert response.status_code == 200
    assert b"Review this" in response.content
    assert hidden.status_code == 302
    comment.refresh_from_db()
    assert comment.moderation_state == "hidden"
    assert comment.moderation_reason == "needs review"

    client.post(
        reverse("comments_studio_moderate", args=(comment.pk,)),
        {"action": "show"},
    )
    comment.refresh_from_db()
    assert comment.moderation_state == "visible"


def test_privacy_export_includes_owned_comments_and_votes():
    member = account("member@example.com")
    other = account("other@example.com")
    comment = create_comment(content_id=uuid.uuid4(), user=member, body="Owned body")
    CommentVote.objects.create(comment=comment, user=other)

    member_export = build_user_data_export(member)
    other_export = build_user_data_export(other)

    assert member_export["comments"][0]["body"] == "Owned body"
    assert member_export["comment_votes"] == []
    assert other_export["comment_votes"][0]["comment_id"] == comment.pk
