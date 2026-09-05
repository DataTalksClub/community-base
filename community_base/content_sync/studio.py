from __future__ import annotations

import uuid

from django.contrib import messages
from django.db import transaction
from django.db.models import Count
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache

from community_base.content_sync.forms import ContentSourceForm
from community_base.content_sync.models import ContentSource, SyncLog, SyncStatus
from community_base.content_sync.queue import queue_source_sync
from community_base.jobs.models import JobIntent
from community_base.kernel.decorators import staff_required


@never_cache
@staff_required
def sources_list(request):
    return render(
        request,
        "community_base/content_sync/sources.html",
        {"sources": ContentSource.objects.all()},
    )


@never_cache
@staff_required
def source_edit(request, source_id):
    source = get_object_or_404(ContentSource, pk=source_id)
    form = ContentSourceForm(request.POST or None, instance=source)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Content source saved.")
        return redirect("community_base_content_sources")
    return render(
        request,
        "community_base/content_sync/source_form.html",
        {"source": source, "form": form},
    )


@staff_required
def source_sync(request, source_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    source = get_object_or_404(ContentSource, pk=source_id)
    force = request.POST.get("force") == "1"
    if not source.is_enabled and not force:
        messages.error(request, "Enable this source or explicitly force the sync.")
        return redirect("community_base_content_sources")
    batch_id = uuid.uuid4()
    with transaction.atomic():
        queue_source_sync(source, key=f"studio:{batch_id}", batch_id=batch_id, force=force)
        ContentSource.objects.filter(pk=source.pk).update(last_sync_status=SyncStatus.QUEUED)
    messages.success(request, "Content sync queued.")
    return redirect("community_base_content_sync_history")


@never_cache
@staff_required
def history(request):
    logs = SyncLog.objects.select_related("source")
    source_slug = request.GET.get("source", "")
    if source_slug:
        logs = logs.filter(source__slug=source_slug)
    return render(
        request,
        "community_base/content_sync/history.html",
        {
            "logs": logs[:200],
            "sources": ContentSource.objects.all(),
            "selected_source": source_slug,
        },
    )


@never_cache
@staff_required
def worker(request):
    active_statuses = (
        JobIntent.Status.PENDING,
        JobIntent.Status.SUBMITTED,
        JobIntent.Status.RUNNING,
        JobIntent.Status.FAILED,
        JobIntent.Status.DEAD,
    )
    counts = {
        row["status"]: row["count"]
        for row in JobIntent.objects.filter(
            handler="cb_content_sync.sync_source", status__in=active_statuses
        )
        .values("status")
        .annotate(count=Count("id"))
    }
    return render(
        request,
        "community_base/content_sync/worker.html",
        {
            "counts": [(status, counts.get(status, 0)) for status in active_statuses],
            "locked_sources": ContentSource.objects.filter(sync_locked_at__isnull=False),
        },
    )
