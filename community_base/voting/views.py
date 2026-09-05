import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from community_base.kernel.access import level_label
from community_base.voting.models import Poll, PollOption, PollVote
from community_base.voting.services import (
    PollClosed,
    VoteLimitReached,
    VotingAccessDenied,
    VotingError,
    available_polls,
    can_view_poll,
    can_vote_in_poll,
    poll_options,
    propose,
)
from community_base.voting.services import toggle_vote as toggle_vote_service


def _private(response):
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Pragma"] = "no-cache"
    return response


def _json_body(request):
    try:
        value = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise VotingError("Invalid request body") from None
    if not isinstance(value, dict):
        raise VotingError("Invalid request body")
    return value


@require_GET
@never_cache
def poll_list(request):
    rows = tuple(
        {
            "poll": poll,
            "options_count": poll.options_count,
            "total_votes": poll.total_votes,
        }
        for poll in available_polls(request.user)
    )
    return _private(render(request, "voting/poll_list.html", {"polls": rows}))


@require_GET
@never_cache
def poll_detail(request, poll_id):
    poll = get_object_or_404(Poll, pk=poll_id)
    if not can_view_poll(poll, request.user):
        return _private(
            render(
                request,
                "voting/poll_detail.html",
                {
                    "poll": poll,
                    "is_gated": True,
                    "required_level_label": level_label(poll.required_level),
                },
            )
        )
    options = poll_options(poll, request.user)
    user_vote_count = 0
    if request.user.is_authenticated:
        user_vote_count = PollVote.objects.filter(poll=poll, user=request.user).count()
    is_closed = poll.is_closed
    context = {
        "poll": poll,
        "options": options,
        "is_gated": False,
        "is_closed": is_closed,
        "can_vote": not is_closed and can_vote_in_poll(poll, request.user),
        "user_vote_count": user_vote_count,
        "max_votes": poll.max_votes_per_user,
        "votes_remaining": max(poll.max_votes_per_user - user_vote_count, 0),
        "allow_proposals": poll.allow_proposals and not is_closed,
    }
    return _private(render(request, "voting/poll_detail.html", context))


@require_POST
def vote_toggle(request, poll_id):
    if not request.user.is_authenticated:
        return _private(JsonResponse({"error": "Authentication required"}, status=401))
    poll = get_object_or_404(Poll, pk=poll_id)
    try:
        option_id = _json_body(request).get("option_id")
        if not option_id:
            raise VotingError("option_id is required")
        transition = toggle_vote_service(poll=poll, option_id=option_id, user=request.user)
    except PollOption.DoesNotExist:
        return _private(JsonResponse({"error": "Option not found"}, status=404))
    except (PollClosed, VotingAccessDenied) as error:
        return _private(JsonResponse({"error": str(error)}, status=403))
    except (VoteLimitReached, VotingError) as error:
        return _private(JsonResponse({"error": str(error)}, status=400))
    return _private(
        JsonResponse(
            {
                "status": "success",
                "action": transition.action,
                "option_id": str(transition.option_id),
                "vote_count": transition.vote_count,
                "votes_remaining": transition.votes_remaining,
            }
        )
    )


@require_POST
def propose_option(request, poll_id):
    if not request.user.is_authenticated:
        return _private(JsonResponse({"error": "Authentication required"}, status=401))
    poll = get_object_or_404(Poll, pk=poll_id)
    try:
        body = _json_body(request)
        option = propose(
            poll=poll,
            user=request.user,
            title=body.get("title", ""),
            description=body.get("description", ""),
        )
    except (PollClosed, VotingAccessDenied) as error:
        return _private(JsonResponse({"error": str(error)}, status=403))
    except VotingError as error:
        return _private(JsonResponse({"error": str(error)}, status=400))
    return _private(
        JsonResponse(
            {
                "status": "success",
                "option_id": str(option.pk),
                "title": option.title,
                "description": option.description,
            },
            status=201,
        )
    )
