from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from community_base.community.models import (
    BookedCall,
    CallHost,
    CommunityAuditLog,
    SlackAccessGrant,
    UnmatchedBookedCall,
)
from community_base.community.studio_forms import CallHostForm
from community_base.kernel.decorators import staff_required
from community_base.studio.utils import studio_pagination_context


def _page(request, rows):
    return studio_pagination_context(request, rows)["page"]


@staff_required
def access_list(request):
    rows = SlackAccessGrant.objects.select_related("user")
    search = request.GET.get("q", "").strip()
    if search:
        rows = rows.filter(user__email__icontains=search)
    return render(
        request,
        "community_base/community/studio/access_list.html",
        {"grants": _page(request, rows), "q": search},
    )


@staff_required
def audit_list(request):
    rows = CommunityAuditLog.objects.select_related("user")
    search = request.GET.get("q", "").strip()
    if search:
        rows = rows.filter(
            Q(user__email__icontains=search)
            | Q(action__icontains=search)
            | Q(details__icontains=search)
        )
    return render(
        request,
        "community_base/community/studio/audit_list.html",
        {"audit_records": _page(request, rows), "q": search},
    )


@staff_required
def call_host_list(request):
    return render(
        request,
        "community_base/community/studio/call_host_list.html",
        {"hosts": CallHost.objects.all()},
    )


def _call_host_form(request, instance=None):
    form = CallHostForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("community_studio_call_host_list")
    return render(
        request,
        "community_base/community/studio/call_host_form.html",
        {"form": form, "object": instance},
        status=400 if request.method == "POST" else 200,
    )


@staff_required
def call_host_create(request):
    return _call_host_form(request)


@staff_required
def call_host_edit(request, host_id):
    return _call_host_form(request, get_object_or_404(CallHost, pk=host_id))


@staff_required
def booked_call_list(request):
    rows = BookedCall.objects.select_related("host", "member")
    return render(
        request,
        "community_base/community/studio/booked_call_list.html",
        {"booked_calls": _page(request, rows)},
    )


@staff_required
def unmatched_call_list(request):
    rows = UnmatchedBookedCall.objects.select_related("member")
    return render(
        request,
        "community_base/community/studio/unmatched_call_list.html",
        {"unmatched_calls": _page(request, rows)},
    )
