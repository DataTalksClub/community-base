import re
from dataclasses import dataclass

from community_base.kernel.access import can_access

TARGET_KEY = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_targets = {}


def default_can_view(poll, user):
    return can_access(user, poll)


def default_can_vote(poll, user):
    return bool(getattr(user, "is_authenticated", False)) and can_access(user, poll)


def no_recipients(_poll, _event, _actor):
    return ()


@dataclass(frozen=True, slots=True)
class VotingTarget:
    key: str
    can_view: object
    can_vote: object
    recipients: object

    def recipient_ids(self, poll, *, event, actor=None):
        values = self.recipients(poll, event, actor) or ()
        actor_id = getattr(actor, "pk", None)
        return tuple(
            sorted(
                {
                    int(getattr(value, "pk", value))
                    for value in values
                    if getattr(value, "pk", value) is not None
                    and int(getattr(value, "pk", value)) != actor_id
                }
            )
        )


def register_voting_target(
    key,
    *,
    can_view=default_can_view,
    can_vote=default_can_vote,
    recipients=no_recipients,
):
    if not isinstance(key, str) or not TARGET_KEY.fullmatch(key):
        raise ValueError("invalid voting target key")
    if not all(callable(item) for item in (can_view, can_vote, recipients)):
        raise TypeError("voting target callbacks must be callable")
    target = VotingTarget(key, can_view, can_vote, recipients)
    existing = _targets.get(key)
    if existing is not None:
        if existing != target:
            raise ValueError(f"voting target is already registered: {key}")
        return existing
    _targets[key] = target
    return target


def voting_target_for(poll):
    return _targets.get(
        poll.poll_type,
        VotingTarget(poll.poll_type, default_can_view, default_can_vote, no_recipients),
    )


def registered_voting_targets():
    return tuple(_targets[key] for key in sorted(_targets))


def _clear():
    _targets.clear()
