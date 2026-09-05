# Voting

Install `community_base.voting` to run member polls with multiple options, proposals and vote
limits. The app keeps the Django label `voting` for the later donor migration squash, but its
initial migration remains provisional until C3.7 verifies the donor schema.

## Installation

Install voting after accounts and the kernel.

```python
INSTALLED_APPS = [
    "community_base.kernel",
    "community_base.accounts",
    "community_base.voting",
]
```

Mount the public pages and JSON routes.

```python
urlpatterns = [
    path("", include("community_base.voting.urls")),
]
```

Run migrations after installing the app.

```bash
python manage.py migrate
```

## Configure access

Voting stores `required_level` on each poll and calls the site's configured
`COMMUNITY_BASE["ACCESS_POLICY"]` for reads and writes.

AISL uses these default poll levels:

```python
COMMUNITY_BASE = {
    "VOTING_POLL_LEVELS": {"topic": 20, "course": 30},
}
```

A site that grants all signed-in members access can map both types to the registered level:

```python
COMMUNITY_BASE = {
    "ACCESS_POLICY": "community_base.kernel.access.RegisteredOnlyPolicy",
    "VOTING_POLL_LEVELS": {"topic": 5, "course": 5},
}
```

`Poll.save()` selects the configured level for its `poll_type`. Keep both built-in types in the
mapping when overriding their levels.

## Register site behavior

Register a poll-type adapter when access or recipient selection needs more context than
`required_level`. Registration belongs in the site's app startup code.

```python
from community_base.voting.registry import register_voting_target

register_voting_target(
    "topic",
    can_view=lambda poll, user: user.is_authenticated and user.can_view_poll(poll),
    can_vote=lambda poll, user: user.is_authenticated and user.can_vote_in_poll(poll),
    recipients=lambda poll, event, actor: poll_notification_recipients(poll, event, actor),
)
```

The package removes the actor from recipient IDs. Voting still rejects anonymous writes even when
an adapter returns `True`.

## Public behavior

The package preserves four route names and paths:

- `poll_list`: `/vote`
- `poll_detail`: `/vote/<poll_id>`
- `vote_toggle`: `/api/vote/<poll_id>/vote`
- `propose_option`: `/api/vote/<poll_id>/propose`

Members toggle their own votes through `vote_toggle`. The server ignores any submitted user ID,
checks that the option belongs to the poll, serializes transitions per poll and enforces
`max_votes_per_user`. The API rejects votes and proposals after a poll closes or expires.

The public templates extend `base.html` and use the package `cb-` class hooks. Override
`voting/poll_list.html` or `voting/poll_detail.html` in a site to change the markup. Keep the data
attributes used by `community_base/voting.js` when retaining the packaged controller.

All personalized pages and JSON responses use private no-store cache headers. Public templates
don't display proposal owners' email addresses.

## Events and privacy

The app sends three Django events without importing notifications or site modules:

- `poll_opened` after an administrator creates or reopens a poll.
- `proposal_created` after the proposal transaction commits.
- `vote_changed` after a vote or unvote transaction commits.

Each event includes adapter-derived `recipient_ids`, so a site receiver can turn those events into
C3.5a notifications. Account privacy exports include only the member's poll votes and proposals.
