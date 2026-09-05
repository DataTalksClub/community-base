from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from community_base.comments.models import Comment
from community_base.comments.services import moderate_comment
from community_base.kernel.decorators import staff_required
from community_base.studio.utils import studio_pagination_context


@staff_required
def comment_list(request):
    rows = Comment.objects.select_related("user", "parent", "moderated_by")
    search = request.GET.get("q", "").strip()
    if search:
        rows = rows.filter(
            Q(user__email__icontains=search)
            | Q(body__icontains=search)
            | Q(content_id__icontains=search)
        )
    return render(
        request,
        "comments/studio/comment_list.html",
        {"comments": studio_pagination_context(request, rows)["page"], "q": search},
    )


@require_POST
@staff_required
def comment_moderate(request, comment_id):
    comment = get_object_or_404(Comment, pk=comment_id)
    action = request.POST.get("action")
    if action not in {"hide", "show"}:
        return redirect("comments_studio_list")
    moderate_comment(
        comment,
        moderator=request.user,
        hidden=action == "hide",
        reason=request.POST.get("reason", ""),
    )
    return redirect("comments_studio_list")
