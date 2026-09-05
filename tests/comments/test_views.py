import json
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.urls import reverse

from community_base.comments.models import Comment
from community_base.comments.registry import register_comment_target
from community_base.comments.services import create_comment, moderate_comment
from community_base.content_sync.models import ContentSource

pytestmark = pytest.mark.django_db(transaction=True)


def account(email, **kwargs):
    return get_user_model().objects.create_user(email=email, **kwargs)


def post_json(client, url, payload):
    return client.post(url, json.dumps(payload), content_type="application/json")


def assert_private(response):
    assert "no-store" in response["Cache-Control"]


def test_fixture_target_supports_public_read_and_authenticated_write(client):
    target = ContentSource.objects.create(slug="fixture", repo_name="owner/fixture")
    register_comment_target("fixture", ContentSource, content_id_field="id")
    endpoint = reverse("comments_endpoint", args=(target.pk,))

    anonymous = client.get(endpoint)
    assert anonymous.status_code == 200
    assert anonymous.json() == {"comments": []}
    assert post_json(client, endpoint, {"body": "Question"}).status_code == 401

    user = account("member@example.com", first_name="Ada", last_name="Member")
    client.force_login(user)
    created = post_json(client, endpoint, {"body": "Question"})

    assert created.status_code == 201
    assert created.json()["user_name"] == "Ada Member"
    assert Comment.objects.get().target == target
    assert_private(created)


def test_private_target_returns_404_for_read_and_403_for_write(client):
    target = ContentSource.objects.create(slug="private", repo_name="owner/private")
    owner = account("owner@example.com")
    other = account("other@example.com")
    register_comment_target(
        "private",
        ContentSource,
        content_id_field="id",
        can_read=lambda target, user: user == owner,
        can_write=lambda target, user: user == owner,
    )
    endpoint = reverse("comments_endpoint", args=(target.pk,))
    client.force_login(other)

    assert client.get(endpoint).status_code == 404
    assert post_json(client, endpoint, {"body": "Denied"}).status_code == 403


def test_list_orders_questions_by_votes_and_replies_oldest_first(client):
    content_id = uuid.uuid4()
    first = account("first@example.com")
    second = account("second@example.com")
    parent = create_comment(content_id=content_id, user=first, body="Popular")
    older = create_comment(content_id=content_id, user=second, body="Older", parent=parent)
    newer = create_comment(content_id=content_id, user=first, body="Newer", parent=parent)
    other = create_comment(content_id=content_id, user=second, body="Other")
    parent.votes.create(user=second)
    client.force_login(second)

    response = client.get(reverse("comments_endpoint", args=(content_id,)))

    rows = response.json()["comments"]
    assert [row["id"] for row in rows] == [parent.pk, other.pk]
    assert [row["id"] for row in rows[0]["replies"]] == [older.pk, newer.pk]
    assert rows[0]["vote_count"] == 1
    assert rows[0]["user_voted"] is True


def test_hidden_comments_and_replies_are_not_listed(client):
    content_id = uuid.uuid4()
    user = account("member@example.com")
    staff = account("staff@example.com", is_staff=True)
    visible = create_comment(content_id=content_id, user=user, body="Visible")
    hidden = create_comment(content_id=content_id, user=user, body="Hidden")
    reply = create_comment(content_id=content_id, user=user, body="Hidden reply", parent=visible)
    moderate_comment(hidden, moderator=staff, hidden=True)
    moderate_comment(reply, moderator=staff, hidden=True)

    response = client.get(reverse("comments_endpoint", args=(content_id,)))

    assert [row["id"] for row in response.json()["comments"]] == [visible.pk]
    assert response.json()["comments"][0]["replies"] == []
    assert b"Hidden" not in response.content


def test_create_validates_json_and_body(client, settings):
    settings.COMMUNITY_BASE = {"COMMENTS_MAX_BODY_LENGTH": 5}
    content_id = uuid.uuid4()
    endpoint = reverse("comments_endpoint", args=(content_id,))
    client.force_login(account("member@example.com"))

    assert client.post(endpoint, b"no", content_type="application/json").status_code == 400
    assert post_json(client, endpoint, {"body": ""}).json()["error"] == "body_required"
    assert post_json(client, endpoint, {"body": "123456"}).json()["error"] == "body_too_long"


def test_reply_and_vote_routes_preserve_top_level_invariants(client):
    content_id = uuid.uuid4()
    user = account("member@example.com")
    parent = create_comment(content_id=content_id, user=user, body="Question")
    client.force_login(user)

    reply_response = post_json(
        client, reverse("comments_reply", args=(parent.pk,)), {"body": "Answer"}
    )
    reply = Comment.objects.get(pk=reply_response.json()["id"])
    first_vote = client.post(reverse("comments_vote", args=(parent.pk,)))
    second_vote = client.post(reverse("comments_vote", args=(parent.pk,)))

    assert reply_response.status_code == 201
    assert first_vote.json() == {"voted": True, "vote_count": 1}
    assert second_vote.json() == {"voted": False, "vote_count": 0}
    assert client.post(reverse("comments_vote", args=(reply.pk,))).status_code == 400
    assert (
        post_json(
            client, reverse("comments_reply", args=(reply.pk,)), {"body": "Nested"}
        ).status_code
        == 400
    )


def test_comment_thread_template_uses_stable_endpoint_and_auth_state(rf):
    content_id = uuid.uuid4()
    request = rf.get("/lesson/")
    request.user = type("Anonymous", (), {"is_authenticated": False})()

    rendered = Template("{% load comment_tags %}{% comment_thread content_id %}").render(
        Context({"request": request, "content_id": content_id})
    )

    assert reverse("comments_endpoint", args=(content_id,)) in rendered
    assert "Sign in to comment" in rendered

    request.user = account("member@example.com")
    rendered = Template("{% load comment_tags %}{% comment_thread content_id %}").render(
        Context({"request": request, "content_id": content_id})
    )
    assert "data-comment-form" in rendered


def test_unsupported_method_is_405(client):
    response = client.put(reverse("comments_endpoint", args=(uuid.uuid4(),)))

    assert response.status_code == 405
    assert response.json() == {"error": "Method not allowed"}
