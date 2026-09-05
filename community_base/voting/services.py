from dataclasses import dataclass

from django.db import transaction
from django.db.models import Count

from community_base.voting.models import Poll, PollOption, PollVote
from community_base.voting.registry import voting_target_for
from community_base.voting.signals import poll_opened, proposal_created, vote_changed


class VotingError(ValueError):
    code = "invalid_vote"


class VotingAccessDenied(VotingError):
    code = "access_denied"


class PollClosed(VotingError):
    code = "poll_closed"


class VoteLimitReached(VotingError):
    code = "vote_limit_reached"


@dataclass(frozen=True, slots=True)
class VoteTransition:
    action: str
    option_id: object
    vote_count: int
    votes_remaining: int


def can_view_poll(poll, user):
    return bool(voting_target_for(poll).can_view(poll, user))


def can_vote_in_poll(poll, user):
    return bool(getattr(user, "is_authenticated", False)) and bool(
        voting_target_for(poll).can_vote(poll, user)
    )


def available_polls(user):
    return tuple(
        poll
        for poll in Poll.objects.filter(status="open").prefetch_related("options", "votes")
        if not poll.is_closed and can_view_poll(poll, user)
    )


def poll_options(poll, user):
    voted = set()
    if getattr(user, "is_authenticated", False):
        voted = set(poll.votes.filter(user=user).values_list("option_id", flat=True))
    rows = poll.options.annotate(vote_count_value=Count("votes")).order_by(
        "-vote_count_value", "created_at"
    )
    return tuple(
        {"option": option, "vote_count": option.vote_count_value, "user_voted": option.pk in voted}
        for option in rows
    )


@transaction.atomic
def toggle_vote(*, poll, option_id, user):
    poll = Poll.objects.select_for_update().get(pk=poll.pk)
    if poll.is_closed:
        raise PollClosed("Poll is closed")
    if not can_vote_in_poll(poll, user):
        raise VotingAccessDenied("Insufficient access level")
    option = PollOption.objects.filter(pk=option_id, poll=poll).first()
    if option is None:
        raise PollOption.DoesNotExist
    existing = PollVote.objects.filter(poll=poll, option=option, user=user).first()
    if existing is not None:
        existing.delete()
        action = "unvoted"
    else:
        current_count = PollVote.objects.filter(poll=poll, user=user).count()
        if current_count >= poll.max_votes_per_user:
            raise VoteLimitReached(f"Maximum {poll.max_votes_per_user} votes per poll")
        PollVote.objects.create(poll=poll, option=option, user=user)
        action = "voted"
    vote_count = PollVote.objects.filter(option=option).count()
    user_count = PollVote.objects.filter(poll=poll, user=user).count()
    target = voting_target_for(poll)
    recipient_ids = target.recipient_ids(poll, event=action, actor=user)
    transaction.on_commit(
        lambda: vote_changed.send(
            sender=PollVote,
            poll=poll,
            option=option,
            user=user,
            action=action,
            recipient_ids=recipient_ids,
        )
    )
    return VoteTransition(
        action=action,
        option_id=option.pk,
        vote_count=vote_count,
        votes_remaining=max(poll.max_votes_per_user - user_count, 0),
    )


@transaction.atomic
def propose(*, poll, user, title, description=""):
    poll = Poll.objects.select_for_update().get(pk=poll.pk)
    if poll.is_closed:
        raise PollClosed("Poll is closed")
    if not poll.allow_proposals:
        raise VotingAccessDenied("Proposals are not allowed for this poll")
    if not can_vote_in_poll(poll, user):
        raise VotingAccessDenied("Insufficient access level")
    title = str(title or "").strip()
    description = str(description or "").strip()
    if not title:
        raise VotingError("Title is required")
    if len(title) > 300:
        raise VotingError("Title must be 300 characters or fewer")
    option = PollOption.objects.create(
        poll=poll, title=title, description=description, proposed_by=user
    )
    recipient_ids = voting_target_for(poll).recipient_ids(
        poll, event="proposal_created", actor=user
    )
    transaction.on_commit(
        lambda: proposal_created.send(
            sender=PollOption,
            poll=poll,
            option=option,
            user=user,
            recipient_ids=recipient_ids,
        )
    )
    return option


def emit_poll_opened(poll, *, actor=None):
    recipient_ids = voting_target_for(poll).recipient_ids(poll, event="poll_opened", actor=actor)
    poll_opened.send(
        sender=Poll,
        poll=poll,
        actor=actor,
        recipient_ids=recipient_ids,
    )
    return recipient_ids
