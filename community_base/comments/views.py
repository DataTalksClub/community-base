import json

from django.db.models import Count, Prefetch
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from community_base.comments.models import Comment
from community_base.comments.services import (
    can_read_thread,
    can_write_thread,
    create_comment,
    toggle_comment_vote,
)
from community_base.kernel.responses import no_store


def _display_name(user):
    name = user.get_full_name().strip()
    return name or user.email


def _json_body(request):
    try:
        data = json.loads(request.body)
    except (TypeError, ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _reply_data(reply):
    return {
        "id": reply.pk,
        "body": reply.body,
        "user_name": _display_name(reply.user),
        "created_at": reply.created_at.isoformat(),
    }


def comments_endpoint(request, content_id):
    if request.method == "GET":
        return list_comments(request, content_id)
    if request.method == "POST":
        return create_comment_view(request, content_id)
    return no_store(JsonResponse({"error": "Method not allowed"}, status=405))


def list_comments(request, content_id):
    if not can_read_thread(content_id, request.user):
        return no_store(JsonResponse({"error": "Not found"}, status=404))
    visible_replies = Comment.objects.filter(
        moderation_state=Comment.ModerationState.VISIBLE
    ).select_related("user")
    rows = (
        Comment.objects.filter(
            content_id=content_id,
            parent__isnull=True,
            moderation_state=Comment.ModerationState.VISIBLE,
        )
        .select_related("user")
        .prefetch_related(Prefetch("replies", queryset=visible_replies))
        .annotate(vote_count=Count("votes"))
        .order_by("-vote_count", "-created_at")
    )
    voted_ids = set()
    if request.user.is_authenticated:
        voted_ids = set(
            request.user.comment_votes.filter(comment__content_id=content_id).values_list(
                "comment_id", flat=True
            )
        )
    return no_store(
        JsonResponse(
            {
                "comments": [
                    {
                        "id": comment.pk,
                        "body": comment.body,
                        "user_name": _display_name(comment.user),
                        "created_at": comment.created_at.isoformat(),
                        "vote_count": comment.vote_count,
                        "user_voted": comment.pk in voted_ids,
                        "replies": [
                            _reply_data(reply)
                            for reply in sorted(
                                comment.replies.all(), key=lambda row: row.created_at
                            )
                        ],
                    }
                    for comment in rows
                ]
            }
        )
    )


def create_comment_view(request, content_id):
    if not request.user.is_authenticated:
        return no_store(JsonResponse({"error": "Authentication required"}, status=401))
    if not can_write_thread(content_id, request.user):
        return no_store(JsonResponse({"error": "Not allowed"}, status=403))
    data = _json_body(request)
    if data is None:
        return no_store(JsonResponse({"error": "Invalid JSON"}, status=400))
    try:
        comment = create_comment(
            content_id=content_id,
            user=request.user,
            body=data.get("body", ""),
        )
    except ValueError as error:
        code = "body_too_long" if "too long" in str(error) else "body_required"
        return no_store(JsonResponse({"error": code}, status=400))
    return no_store(
        JsonResponse(
            {
                "id": comment.pk,
                "body": comment.body,
                "user_name": _display_name(request.user),
                "created_at": comment.created_at.isoformat(),
                "vote_count": 0,
                "user_voted": False,
                "replies": [],
            },
            status=201,
        )
    )


@require_POST
def reply_to_comment(request, comment_id):
    if not request.user.is_authenticated:
        return no_store(JsonResponse({"error": "Authentication required"}, status=401))
    parent = Comment.objects.filter(pk=comment_id).first()
    if parent is None:
        return no_store(JsonResponse({"error": "Comment not found"}, status=404))
    if parent.parent_id:
        return no_store(JsonResponse({"error": "Cannot reply to a reply"}, status=400))
    if not can_write_thread(parent.content_id, request.user):
        return no_store(JsonResponse({"error": "Not allowed"}, status=403))
    data = _json_body(request)
    if data is None:
        return no_store(JsonResponse({"error": "Invalid JSON"}, status=400))
    try:
        reply = create_comment(
            content_id=parent.content_id,
            user=request.user,
            parent=parent,
            body=data.get("body", ""),
        )
    except ValueError as error:
        code = "body_too_long" if "too long" in str(error) else "body_required"
        return no_store(JsonResponse({"error": code}, status=400))
    return no_store(JsonResponse(_reply_data(reply), status=201))


@require_POST
def toggle_vote(request, comment_id):
    if not request.user.is_authenticated:
        return no_store(JsonResponse({"error": "Authentication required"}, status=401))
    comment = Comment.objects.filter(pk=comment_id).first()
    if comment is None:
        return no_store(JsonResponse({"error": "Comment not found"}, status=404))
    if comment.parent_id:
        return no_store(JsonResponse({"error": "Cannot vote on a reply"}, status=400))
    if not can_write_thread(comment.content_id, request.user):
        return no_store(JsonResponse({"error": "Not allowed"}, status=403))
    voted, count = toggle_comment_vote(comment=comment, user=request.user)
    return no_store(JsonResponse({"voted": voted, "vote_count": count}))
