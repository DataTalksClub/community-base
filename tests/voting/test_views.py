import json
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from community_base.accounts.models import User
from community_base.voting.models import Poll, PollOption, PollVote
from community_base.voting.registry import register_voting_target

pytestmark = pytest.mark.django_db


def user(email="member@example.com"):
    return User.objects.create_user(email=email, password="test-password")


def poll(**values):
    values.setdefault("title", "Next topic")
    return Poll.objects.create(**values)


def option(item, title="RAG"):
    return PollOption.objects.create(poll=item, title=title)


def post_json(client, path, body):
    return client.post(path, data=json.dumps(body), content_type="application/json")


def test_testproject_lists_fixture_poll_without_site_imports(client):
    member = user()
    item = poll(description="Pick one")
    option(item)
    client.force_login(member)

    response = client.get("/vote")

    assert response.status_code == 200
    assert response.context["polls"][0]["poll"] == item
    assert b"Next topic" in response.content
    assert "private" in response.headers["Cache-Control"]
    assert "no-store" in response.headers["Cache-Control"]


def test_anonymous_list_hides_registered_polls_and_offers_sign_in(client):
    poll()

    response = client.get("/vote")

    assert response.status_code == 200
    assert response.context["polls"] == ()
    assert b"Sign in" in response.content


def test_registered_target_can_hide_poll_from_list(client):
    member = user()
    poll()
    register_voting_target(
        "topic", can_view=lambda _poll, _user: False, can_vote=lambda _poll, _user: False
    )
    client.force_login(member)

    assert client.get("/vote").context["polls"] == ()


def test_detail_sorts_options_and_marks_the_current_members_vote(client):
    member = user()
    other = user("other@example.com")
    item = poll(max_votes_per_user=3)
    first = option(item, "First")
    second = option(item, "Second")
    PollVote.objects.create(poll=item, option=second, user=member)
    PollVote.objects.create(poll=item, option=second, user=other)
    client.force_login(member)

    response = client.get(f"/vote/{item.pk}")

    assert response.status_code == 200
    assert [row["option"] for row in response.context["options"]] == [second, first]
    assert response.context["options"][0]["user_voted"] is True
    assert response.context["votes_remaining"] == 2


def test_denied_detail_uses_gated_page_without_options(client):
    item = poll()
    option(item, "Private option")

    response = client.get(f"/vote/{item.pk}")

    assert response.status_code == 200
    assert response.context["is_gated"] is True
    assert b"Private option" not in response.content


def test_closed_poll_shows_results_without_write_controls(client):
    member = user()
    item = poll(status="closed", allow_proposals=True)
    option(item)
    client.force_login(member)

    response = client.get(f"/vote/{item.pk}")

    assert response.context["is_closed"] is True
    assert response.context["can_vote"] is False
    assert response.context["allow_proposals"] is False


def test_vote_endpoint_requires_authentication_and_owns_vote(client):
    member = user()
    other = user("other@example.com")
    item = poll()
    choice = option(item)
    path = f"/api/vote/{item.pk}/vote"
    assert post_json(client, path, {"option_id": str(choice.pk)}).status_code == 401

    client.force_login(member)
    response = post_json(client, path, {"option_id": str(choice.pk), "user_id": other.pk})

    assert response.status_code == 200
    assert response.json()["action"] == "voted"
    assert PollVote.objects.filter(user=member, option=choice).exists()
    assert not PollVote.objects.filter(user=other, option=choice).exists()


def test_vote_endpoint_toggles_and_returns_counts(client):
    member = user()
    item = poll(max_votes_per_user=2)
    choice = option(item)
    client.force_login(member)
    path = f"/api/vote/{item.pk}/vote"

    first = post_json(client, path, {"option_id": str(choice.pk)}).json()
    second = post_json(client, path, {"option_id": str(choice.pk)}).json()

    assert (first["action"], first["vote_count"], first["votes_remaining"]) == (
        "voted",
        1,
        1,
    )
    assert (second["action"], second["vote_count"], second["votes_remaining"]) == (
        "unvoted",
        0,
        2,
    )


@pytest.mark.parametrize("body", ["not-json", "[]", "{}"])
def test_vote_endpoint_rejects_invalid_bodies(client, body):
    member = user()
    item = poll()
    client.force_login(member)

    response = client.post(f"/api/vote/{item.pk}/vote", data=body, content_type="application/json")

    assert response.status_code == 400
    assert response.headers["Cache-Control"] == "private, no-store, max-age=0"


def test_vote_endpoint_returns_not_found_for_malformed_option_id(client):
    member = user()
    item = poll()
    client.force_login(member)

    response = post_json(client, f"/api/vote/{item.pk}/vote", {"option_id": "not-a-uuid"})

    assert response.status_code == 404


def test_vote_endpoint_rejects_wrong_option_limit_closed_and_expired(client):
    member = user()
    item = poll(max_votes_per_user=1)
    first = option(item, "First")
    second = option(item, "Second")
    other = poll(title="Other")
    wrong = option(other)
    client.force_login(member)
    path = f"/api/vote/{item.pk}/vote"

    assert post_json(client, path, {"option_id": str(wrong.pk)}).status_code == 404
    assert post_json(client, path, {"option_id": str(first.pk)}).status_code == 200
    assert post_json(client, path, {"option_id": str(second.pk)}).status_code == 400
    item.status = "closed"
    item.save()
    assert post_json(client, path, {"option_id": str(first.pk)}).status_code == 403
    item.status = "open"
    item.closes_at = timezone.now() - timedelta(seconds=1)
    item.save()
    assert post_json(client, path, {"option_id": str(first.pk)}).status_code == 403


def test_proposal_endpoint_enforces_policy_and_owns_proposal(client):
    member = user()
    other = user("other@example.com")
    item = poll(allow_proposals=True)
    path = f"/api/vote/{item.pk}/propose"
    assert post_json(client, path, {"title": "RAG"}).status_code == 401
    client.force_login(member)

    response = post_json(
        client,
        path,
        {"title": "  RAG  ", "description": "  Retrieval  ", "user_id": other.pk},
    )

    assert response.status_code == 201
    created = PollOption.objects.get(pk=response.json()["option_id"])
    assert created.proposed_by == member
    assert (created.title, created.description) == ("RAG", "Retrieval")


def test_proposal_endpoint_rejects_invalid_and_disallowed_requests(client):
    member = user()
    item = poll(allow_proposals=False)
    client.force_login(member)
    path = f"/api/vote/{item.pk}/propose"

    assert post_json(client, path, {"title": "RAG"}).status_code == 403
    item.allow_proposals = True
    item.save()
    assert post_json(client, path, {"title": "   "}).status_code == 400
    assert client.post(path, data="bad", content_type="application/json").status_code == 400
    item.status = "closed"
    item.save()
    assert post_json(client, path, {"title": "RAG"}).status_code == 403


def test_missing_poll_and_wrong_methods_return_expected_status(client):
    member = user()
    client.force_login(member)
    missing = uuid.uuid4()
    assert client.get(f"/api/vote/{missing}/vote").status_code == 405
    assert post_json(client, f"/api/vote/{missing}/vote", {}).status_code == 404
