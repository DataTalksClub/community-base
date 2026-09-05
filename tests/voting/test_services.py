from datetime import timedelta

import pytest
from django.utils import timezone

from community_base.accounts.models import User
from community_base.voting.models import Poll, PollOption, PollVote
from community_base.voting.registry import register_voting_target
from community_base.voting.services import (
    PollClosed,
    VoteLimitReached,
    VotingAccessDenied,
    available_polls,
    emit_poll_opened,
    poll_options,
    propose,
    toggle_vote,
)
from community_base.voting.signals import proposal_created, vote_changed

pytestmark = pytest.mark.django_db


def user(email="member@example.com"):
    return User.objects.create_user(email=email, password="test-password")


def poll(**values):
    values.setdefault("title", "Next topic")
    return Poll.objects.create(**values)


def test_registered_target_controls_visibility_and_recipients():
    owner = user("owner@example.com")
    voter = user()
    target = register_voting_target(
        "topic",
        can_view=lambda _poll, visitor: visitor == voter,
        can_vote=lambda _poll, visitor: visitor == voter,
        recipients=lambda _poll, _event, _actor: (owner, voter),
    )
    item = poll()

    assert available_polls(voter) == (item,)
    assert available_polls(owner) == ()
    assert target.recipient_ids(item, event="voted", actor=voter) == (owner.pk,)
    assert emit_poll_opened(item, actor=voter) == (owner.pk,)


def test_vote_toggle_creates_and_removes_only_the_request_users_vote():
    voter = user()
    other = user("other@example.com")
    item = poll(max_votes_per_user=2)
    option = PollOption.objects.create(poll=item, title="RAG")
    PollVote.objects.create(poll=item, option=option, user=other)

    created = toggle_vote(poll=item, option_id=option.pk, user=voter)
    assert created.action == "voted"
    assert created.vote_count == 2
    assert created.votes_remaining == 1
    assert PollVote.objects.filter(poll=item, option=option, user=voter).exists()

    removed = toggle_vote(poll=item, option_id=option.pk, user=voter)
    assert removed.action == "unvoted"
    assert removed.vote_count == 1
    assert PollVote.objects.filter(poll=item, option=option, user=other).exists()


def test_vote_limit_and_wrong_poll_option_are_rejected():
    voter = user()
    item = poll(max_votes_per_user=1)
    first = PollOption.objects.create(poll=item, title="First")
    second = PollOption.objects.create(poll=item, title="Second")
    other_poll = poll(title="Other poll")
    other_option = PollOption.objects.create(poll=other_poll, title="Other")
    toggle_vote(poll=item, option_id=first.pk, user=voter)

    with pytest.raises(VoteLimitReached):
        toggle_vote(poll=item, option_id=second.pk, user=voter)
    with pytest.raises(PollOption.DoesNotExist):
        toggle_vote(poll=item, option_id=other_option.pk, user=voter)


def test_closed_expired_and_denied_polls_reject_votes():
    voter = user()
    closed = poll(status="closed")
    closed_option = PollOption.objects.create(poll=closed, title="Closed")
    with pytest.raises(PollClosed):
        toggle_vote(poll=closed, option_id=closed_option.pk, user=voter)

    expired = poll(title="Expired", closes_at=timezone.now() - timedelta(seconds=1))
    expired_option = PollOption.objects.create(poll=expired, title="Expired")
    with pytest.raises(PollClosed):
        toggle_vote(poll=expired, option_id=expired_option.pk, user=voter)

    denied = poll(title="Denied", poll_type="course")
    denied_option = PollOption.objects.create(poll=denied, title="Denied")
    register_voting_target(
        "course", can_view=lambda _poll, _user: False, can_vote=lambda _poll, _user: False
    )
    with pytest.raises(VotingAccessDenied):
        toggle_vote(poll=denied, option_id=denied_option.pk, user=voter)


def test_options_are_sorted_by_count_and_include_current_vote_state():
    voter = user()
    other = user("other@example.com")
    item = poll()
    first = PollOption.objects.create(poll=item, title="First")
    second = PollOption.objects.create(poll=item, title="Second")
    PollVote.objects.create(poll=item, option=second, user=voter)
    PollVote.objects.create(poll=item, option=second, user=other)

    rows = poll_options(item, voter)
    assert [row["option"] for row in rows] == [second, first]
    assert rows[0]["vote_count"] == 2
    assert rows[0]["user_voted"] is True


def test_proposal_uses_authenticated_owner_and_emits_after_commit(
    django_capture_on_commit_callbacks,
):
    proposer = user()
    recipient = user("recipient@example.com")
    item = poll(allow_proposals=True)
    register_voting_target(
        "topic",
        recipients=lambda _poll, _event, _actor: (recipient,),
    )
    received = []

    def receiver(sender, **kwargs):
        received.append(kwargs)

    proposal_created.connect(receiver, weak=False)
    try:
        with django_capture_on_commit_callbacks(execute=True):
            option = propose(
                poll=item,
                user=proposer,
                title="  Vector search  ",
                description="  Details  ",
            )
    finally:
        proposal_created.disconnect(receiver)

    assert option.proposed_by == proposer
    assert option.title == "Vector search"
    assert option.description == "Details"
    assert received[0]["recipient_ids"] == (recipient.pk,)


def test_vote_signal_reports_transition_after_commit(django_capture_on_commit_callbacks):
    voter = user()
    item = poll()
    option = PollOption.objects.create(poll=item, title="RAG")
    received = []

    def receiver(sender, **kwargs):
        received.append(kwargs)

    vote_changed.connect(receiver, weak=False)
    try:
        with django_capture_on_commit_callbacks(execute=True):
            toggle_vote(poll=item, option_id=option.pk, user=voter)
    finally:
        vote_changed.disconnect(receiver)

    assert received[0]["user"] == voter
    assert received[0]["action"] == "voted"
