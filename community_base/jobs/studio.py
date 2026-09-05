from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from community_base.jobs.backends import get_backend
from community_base.jobs.models import JobIntent
from community_base.jobs.registry import registered_schedules
from community_base.kernel.conf import get
from community_base.kernel.decorators import staff_required


@never_cache
@staff_required
def jobs_list(request):
    statuses = (
        JobIntent.Status.PENDING,
        JobIntent.Status.SUBMITTED,
        JobIntent.Status.RUNNING,
        JobIntent.Status.FAILED,
        JobIntent.Status.DEAD,
    )
    intents = JobIntent.objects.filter(status__in=statuses).order_by(
        "status", "available_at", "created_at"
    )
    schedules = [
        {"definition": definition, "last_run": None, "next_run": None}
        for definition in registered_schedules()
    ]
    _add_django_q_schedule_times(schedules)
    return render(
        request,
        "community_base/jobs/jobs.html",
        {"intents": intents, "schedules": schedules},
    )


@staff_required
def retry_job(request, intent_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    if request.POST.get("confirmation") != "retry":
        messages.error(request, "Type retry to confirm durable job retry.")
        return redirect("community_base_jobs")
    with transaction.atomic():
        intent = get_object_or_404(JobIntent.objects.select_for_update(), id=intent_id)
        if intent.status not in {JobIntent.Status.FAILED, JobIntent.Status.DEAD}:
            messages.error(request, "Only failed or dead jobs can be retried.")
            return redirect("community_base_jobs")
        updated = JobIntent.objects.filter(id=intent.id, status=intent.status).update(
            status=JobIntent.Status.PENDING,
            attempts=0,
            available_at=timezone.now(),
            lease_token=None,
            lease_expires_at=None,
            last_error="",
            updated_at=timezone.now(),
        )
        if updated:
            transaction.on_commit(lambda: get_backend().submit(intent.id), robust=True)
    messages.success(request, "Durable job queued for retry.")
    return redirect("community_base_jobs")


def _add_django_q_schedule_times(schedules: list[dict]) -> None:
    if get("JOBS_BACKEND") != "django_q":
        return
    try:
        from django_q.models import Schedule, Task  # type: ignore[import-untyped]
    except (ImportError, RuntimeError):
        return
    names = [f"community-base:{item['definition'].name}" for item in schedules]
    rows = {row.name: row for row in Schedule.objects.filter(name__in=names)}
    for item in schedules:
        row = rows.get(f"community-base:{item['definition'].name}")
        if row is None:
            continue
        item["next_run"] = row.next_run
        if row.task:
            item["last_run"] = (
                Task.objects.filter(id=row.task).values_list("stopped", flat=True).first()
            )


@staff_required
def discard_job(request, intent_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    if request.POST.get("confirmation") != "discard":
        messages.error(request, "Type discard to confirm durable job discard.")
        return redirect("community_base_jobs")
    with transaction.atomic():
        intent = get_object_or_404(JobIntent.objects.select_for_update(), id=intent_id)
        if intent.status in JobIntent.TERMINAL_STATUSES:
            messages.error(request, "Completed jobs cannot be discarded.")
            return redirect("community_base_jobs")
        updated = JobIntent.objects.filter(
            id=intent.id,
            status=intent.status,
            lease_token=intent.lease_token,
        ).update(
            status=JobIntent.Status.DEAD,
            lease_token=None,
            lease_expires_at=None,
            last_error="discarded_by_operator",
            updated_at=timezone.now(),
        )
    if updated:
        messages.success(request, "Durable job discarded.")
    else:
        messages.error(request, "The job changed before it could be discarded.")
    return redirect("community_base_jobs")
