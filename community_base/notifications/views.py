from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from community_base.notifications.models import Notification
from community_base.notifications.services import (
    mark_all_notifications_read,
    mark_notification_read,
)


def _private(response):
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Pragma"] = "no-cache"
    return response


def _notification_data(notification):
    return {
        "id": notification.pk,
        "title": notification.title,
        "body": notification.body[:80],
        "url": notification.url,
        "notification_type": notification.notification_type,
        "read": notification.read,
        "created_at": notification.created_at.isoformat(),
    }


@login_required
@require_GET
@never_cache
def api_notification_list(request):
    selected_filter = request.GET.get("filter", "all")
    if selected_filter not in {"all", "unread"}:
        return _private(JsonResponse({"ok": False, "error": "invalid_filter"}, status=400))
    rows = Notification.objects.filter(user=request.user)
    if selected_filter == "unread":
        rows = rows.filter(read=False)
    page = Paginator(rows, 20).get_page(request.GET.get("page", 1))
    return _private(
        JsonResponse(
            {
                "notifications": [_notification_data(item) for item in page.object_list],
                "page": page.number,
                "has_next": page.has_next(),
                "total": page.paginator.count,
                "filter": selected_filter,
            }
        )
    )


@login_required
@require_GET
@never_cache
def api_unread_count(request):
    count = Notification.objects.filter(user=request.user, read=False).count()
    return _private(JsonResponse({"count": count}))


@login_required
@require_POST
def api_mark_read(request, notification_id):
    if not mark_notification_read(request.user, notification_id):
        return _private(JsonResponse({"ok": False, "error": "not_found"}, status=404))
    return _private(JsonResponse({"ok": True}))


@login_required
@require_POST
def api_mark_all_read(request):
    count = mark_all_notifications_read(request.user)
    return _private(JsonResponse({"ok": True, "count": count}))


@login_required
@require_GET
@never_cache
def notification_list_page(request):
    selected_filter = request.GET.get("filter", "unread")
    if selected_filter not in {"all", "unread"}:
        selected_filter = "unread"
    rows = Notification.objects.filter(user=request.user)
    if selected_filter == "unread":
        rows = rows.filter(read=False)
    page = Paginator(rows, 20).get_page(request.GET.get("page", 1))
    response = render(
        request,
        "notifications/notification_list.html",
        {
            "active_filter": selected_filter,
            "all_filter_url": "?filter=all",
            "unread_count": Notification.objects.filter(user=request.user, read=False).count(),
            "page_obj": page,
            "pagination_filter_query": f"filter={selected_filter}&",
            "notifications": page.object_list,
        },
    )
    return _private(response)
