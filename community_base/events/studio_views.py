from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from community_base.events.guest_invitations import invite_guest
from community_base.events.models import Event, EventRegistration, EventSeries, Host
from community_base.events.registration import record_attendance
from community_base.events.services import allocate_public_id, cancel_event, publish_event
from community_base.events.studio_forms import (
    EventForm,
    EventSeriesForm,
    GuestInvitationForm,
    HostForm,
    RegistrationStateForm,
)
from community_base.kernel.decorators import staff_required
from community_base.studio.audit import hooks as studio_hooks
from community_base.studio.utils import studio_pagination_context


def _audit(request, event, target, **metadata):
    studio_hooks.audit_writer(
        event=event,
        actor_ref=str(request.user.pk),
        target_ref=str(target.pk),
        metadata=metadata,
    )


def _save_form(request, form_class, *, instance=None):
    previous_status = instance.status if isinstance(instance, Event) else None
    form = form_class(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            item = form.save()
            if isinstance(item, Event):
                if item.status == "upcoming" and previous_status != "upcoming":
                    item = publish_event(item)
                elif item.status == "cancelled" and previous_status != "cancelled":
                    item = cancel_event(item)
                elif item.status == "upcoming" and item.public_id is None:
                    item.public_id = allocate_public_id(item)
        return item
    return form


@staff_required
def event_list(request):
    rows = (
        Event.objects.select_related("event_series")
        .annotate(registration_count=Count("registrations"))
        .order_by("-start_datetime", "pk")
    )
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    if query:
        rows = rows.filter(Q(title__icontains=query) | Q(slug__icontains=query))
    if status:
        rows = rows.filter(status=status)
    return render(
        request,
        "community_base/events/studio/event_list.html",
        {"events": studio_pagination_context(request, rows)["page"], "q": query, "status": status},
    )


@staff_required
def event_create(request):
    result = _save_form(request, EventForm)
    if isinstance(result, Event):
        _audit(request, "events.event.created", result)
        messages.success(request, "Event created.")
        return redirect("events_studio_detail", event_id=result.pk)
    return render(
        request,
        "community_base/events/studio/form.html",
        {"form": result, "kind": "event"},
        status=400 if request.method == "POST" else 200,
    )


@staff_required
def event_detail(request, event_id):
    item = get_object_or_404(Event.objects.select_related("event_series"), pk=event_id)
    return render(
        request,
        "community_base/events/studio/event_detail.html",
        {
            "event": item,
            "registrations": item.registrations.select_related("user"),
            "guest_form": GuestInvitationForm(),
            "state_form": RegistrationStateForm(),
        },
    )


@staff_required
def event_edit(request, event_id):
    item = get_object_or_404(Event, pk=event_id)
    result = _save_form(request, EventForm, instance=item)
    if isinstance(result, Event):
        _audit(request, "events.event.updated", result)
        messages.success(request, "Event updated.")
        return redirect("events_studio_detail", event_id=result.pk)
    return render(
        request,
        "community_base/events/studio/form.html",
        {"form": result, "object": item, "kind": "event"},
        status=400 if request.method == "POST" else 200,
    )


@require_POST
@staff_required
def event_delete(request, event_id):
    item = get_object_or_404(Event, pk=event_id)
    target = item.pk
    try:
        item.delete()
    except ProtectedError:
        messages.error(request, "Events with registrations cannot be deleted.")
    else:
        _audit(request, "events.event.deleted", type("Target", (), {"pk": target})())
        messages.success(request, "Event deleted.")
    return redirect("events_studio_list")


@require_POST
@staff_required
def event_invite_guest(request, event_id):
    item = get_object_or_404(Event, pk=event_id)
    form = GuestInvitationForm(request.POST)
    if form.is_valid():
        try:
            result = invite_guest(item, form.cleaned_data["email"])
        except ValidationError as error:
            messages.error(request, str(error))
        else:
            _audit(
                request,
                "events.guest.invited",
                result.registration,
                event_ref=str(item.pk),
                delivery_ref=str(result.delivery.pk),
            )
            messages.success(request, "Guest invitation queued.")
    else:
        messages.error(request, form.errors.as_text())
    return redirect("events_studio_detail", event_id=item.pk)


@require_POST
@staff_required
def registration_state(request, event_id, registration_id):
    item = get_object_or_404(Event, pk=event_id)
    registration = get_object_or_404(EventRegistration, pk=registration_id, event=item)
    form = RegistrationStateForm(request.POST)
    if form.is_valid():
        target = form.cleaned_data["state"]
        try:
            if target in {"attended", "no_show"}:
                registration, changed = record_attendance(
                    registration, attended=target == "attended"
                )
            else:
                with transaction.atomic():
                    registration = EventRegistration.objects.select_for_update().get(
                        pk=registration.pk
                    )
                    changed = registration.status != EventRegistration.Status.CANCELLED
                    if changed:
                        registration.status = EventRegistration.Status.CANCELLED
                        registration.version += 1
                        registration.save(update_fields=("status", "version", "updated_at"))
        except ValidationError as error:
            messages.error(request, str(error))
        else:
            if changed:
                _audit(request, f"events.registration.{target}", registration)
            messages.success(request, "Registration state updated.")
    else:
        messages.error(request, form.errors.as_text())
    return redirect("events_studio_detail", event_id=item.pk)


def _collection(request, model, template, context_name):
    rows = model.objects.all()
    query = request.GET.get("q", "").strip()
    if query:
        rows = rows.filter(Q(name__icontains=query) | Q(slug__icontains=query))
    return render(request, template, {context_name: rows, "q": query})


@staff_required
def series_list(request):
    return _collection(
        request, EventSeries, "community_base/events/studio/series_list.html", "series_list"
    )


@staff_required
def series_create(request):
    return _named_form(request, EventSeriesForm, "series", "events_studio_series_list")


@staff_required
def series_edit(request, series_id):
    return _named_form(
        request,
        EventSeriesForm,
        "series",
        "events_studio_series_list",
        get_object_or_404(EventSeries, pk=series_id),
    )


@staff_required
def host_list(request):
    return _collection(request, Host, "community_base/events/studio/host_list.html", "hosts")


@staff_required
def host_create(request):
    return _named_form(request, HostForm, "host", "events_studio_host_list")


@staff_required
def host_edit(request, host_id):
    return _named_form(
        request,
        HostForm,
        "host",
        "events_studio_host_list",
        get_object_or_404(Host, pk=host_id),
    )


def _named_form(request, form_class, kind, redirect_name, instance=None):
    result = _save_form(request, form_class, instance=instance)
    if not isinstance(result, form_class):
        action = "updated" if instance is not None else "created"
        _audit(request, f"events.{kind}.{action}", result)
        messages.success(request, f"{kind.title()} {action}.")
        return redirect(redirect_name)
    return render(
        request,
        "community_base/events/studio/form.html",
        {"form": result, "object": instance, "kind": kind},
        status=400 if request.method == "POST" else 200,
    )


@require_POST
@staff_required
def series_delete(request, series_id):
    return _delete_named(request, get_object_or_404(EventSeries, pk=series_id), "series")


@require_POST
@staff_required
def host_delete(request, host_id):
    return _delete_named(request, get_object_or_404(Host, pk=host_id), "host")


def _delete_named(request, item, kind):
    target = item.pk
    try:
        item.delete()
    except ProtectedError:
        messages.error(request, f"This {kind} is still in use.")
    else:
        _audit(request, f"events.{kind}.deleted", type("Target", (), {"pk": target})())
        messages.success(request, f"{kind.title()} deleted.")
    return redirect(f"events_studio_{kind}_list")
