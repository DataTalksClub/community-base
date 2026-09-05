from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import ProtectedError
from django.forms.models import model_to_dict
from django.http import JsonResponse

from community_base.api import route
from community_base.api.errors import APIError
from community_base.api.safety import read_json_object
from community_base.events.feedback import submit_feedback
from community_base.events.guest_invitations import invite_guest
from community_base.events.models import Event, EventRegistration, EventSeries, Host
from community_base.events.registration import register_for_event, unregister_from_event
from community_base.events.services import allocate_public_id
from community_base.events.studio_forms import EventForm, EventSeriesForm, HostForm

OBJECT = {"type": "object"}
COLLECTION = {"type": "object", "properties": {"results": {"type": "array"}}}


def _staff(request):
    if not request.user.is_staff:
        raise APIError(403, "staff_required", "Staff access is required.")


def _event(event_id):
    item = Event.objects.filter(pk=event_id).first()
    if item is None:
        raise APIError(404, "event_not_found", "Event was not found.")
    return item


def _series(series_id):
    item = EventSeries.objects.filter(pk=series_id).first()
    if item is None:
        raise APIError(404, "event_series_not_found", "Event series was not found.")
    return item


def _host(host_id):
    item = Host.objects.filter(pk=host_id).first()
    if item is None:
        raise APIError(404, "event_host_not_found", "Event host was not found.")
    return item


def _iso(value):
    return value.isoformat() if value is not None else None


def serialize_event(item):
    return {
        "id": item.pk,
        "public_id": item.public_id,
        "slug": item.slug,
        "title": item.title,
        "description": item.description,
        "kind": item.kind,
        "platform": item.platform,
        "start_datetime": _iso(item.start_datetime),
        "end_datetime": _iso(item.end_datetime),
        "timezone": item.timezone,
        "location": item.location,
        "required_level": item.required_level,
        "status": item.status,
        "event_series_id": item.event_series_id,
        "series_position": item.series_position,
        "host_ids": list(item.hosts.values_list("pk", flat=True)),
        "recording_url": item.recording_url,
        "materials": item.materials,
        "url": item.get_absolute_url() if item.status in {"upcoming", "completed"} else None,
    }


def serialize_series(item):
    return {
        "id": item.pk,
        "name": item.name,
        "slug": item.slug,
        "description": item.description,
        "cadence": item.cadence,
        "day_of_week": item.day_of_week,
        "start_time": item.start_time.isoformat() if item.start_time else None,
        "timezone": item.timezone,
        "required_level": item.required_level,
        "is_active": item.is_active,
    }


def serialize_host(item):
    return {
        "id": item.pk,
        "name": item.name,
        "slug": item.slug,
        "kind": item.kind,
        "external_ref": item.external_ref,
        "title": item.title,
        "bio": item.bio,
        "photo_url": item.photo_url,
        "email": item.email,
        "is_active": item.is_active,
    }


def serialize_registration(item):
    return {
        "id": str(item.pk),
        "event_id": item.event_id,
        "email": item.normalized_email,
        "status": item.status,
        "version": item.version,
        "created_at": _iso(item.created_at),
    }


def _form_error(form):
    return APIError(
        400,
        "validation_error",
        "Request fields are invalid.",
        details={"fields": form.errors.get_json_data()},
    )


def _model_form(request, form_class, *, instance=None):
    values = read_json_object(request)
    allowed = set(form_class.Meta.fields)
    unknown = set(values) - allowed
    if unknown:
        raise APIError(
            400,
            "unknown_fields",
            "Request contains unsupported fields.",
            details={"fields": sorted(unknown)},
        )
    if instance is None:
        data = values
    else:
        data = model_to_dict(instance, fields=form_class.Meta.fields)
        data.update(values)
    form = form_class(data, instance=instance)
    if not form.is_valid():
        raise _form_error(form)
    item = form.save()
    if isinstance(item, Event) and item.status == "upcoming" and item.public_id is None:
        item.public_id = allocate_public_id(item)
    return item


@route("GET", "events", None, "List events for staff", COLLECTION, authentication="session")
def events_get(request):
    _staff(request)
    return JsonResponse({"results": [serialize_event(item) for item in Event.objects.all()]})


@route("POST", "events", None, "Create an event", OBJECT, OBJECT, authentication="session")
def events_post(request):
    _staff(request)
    return JsonResponse({"event": serialize_event(_model_form(request, EventForm))}, status=201)


@route(
    "GET",
    "events/<int:event_id>",
    None,
    "Read an event for staff",
    OBJECT,
    authentication="session",
)
def event_get(request, event_id):
    _staff(request)
    return JsonResponse({"event": serialize_event(_event(event_id))})


@route(
    "PATCH",
    "events/<int:event_id>",
    None,
    "Update an event",
    OBJECT,
    OBJECT,
    authentication="session",
)
def event_patch(request, event_id):
    _staff(request)
    return JsonResponse(
        {"event": serialize_event(_model_form(request, EventForm, instance=_event(event_id)))}
    )


@route("DELETE", "events/<int:event_id>", None, "Delete an event", OBJECT, authentication="session")
def event_delete(request, event_id):
    _staff(request)
    item = _event(event_id)
    try:
        item.delete()
    except ProtectedError as error:
        raise APIError(409, "event_in_use", "Event is still referenced.") from error
    return JsonResponse({"status": "deleted"})


def _owned_registration(request, event_id):
    item = (
        EventRegistration.objects.select_related("event")
        .filter(event_id=event_id, user=request.user)
        .first()
    )
    if item is None:
        raise APIError(404, "registration_not_found", "Your registration was not found.")
    return item


@route(
    "GET",
    "events/<int:event_id>/registration",
    None,
    "Read your event registration",
    OBJECT,
    authentication="session",
)
def registration_get(request, event_id):
    return JsonResponse(
        {"registration": serialize_registration(_owned_registration(request, event_id))}
    )


@route(
    "POST",
    "events/<int:event_id>/registration",
    None,
    "Register for an event",
    OBJECT,
    OBJECT,
    authentication="session",
)
def registration_post(request, event_id):
    if read_json_object(request):
        raise APIError(400, "unknown_fields", "Registration does not accept request fields.")
    try:
        item, created = register_for_event(_event(event_id), request.user)
    except (PermissionDenied, ValidationError) as error:
        raise APIError(400, "registration_unavailable", str(error)) from error
    return JsonResponse(
        {"registration": serialize_registration(item)}, status=201 if created else 200
    )


@route(
    "DELETE",
    "events/<int:event_id>/registration",
    None,
    "Cancel your event registration",
    OBJECT,
    authentication="session",
)
def registration_delete(request, event_id):
    owned = _owned_registration(request, event_id)
    try:
        item, _changed = unregister_from_event(owned.event, request.user)
    except ValidationError as error:
        raise APIError(400, "registration_unavailable", str(error)) from error
    return JsonResponse({"registration": serialize_registration(item)})


@route(
    "PUT",
    "events/<int:event_id>/feedback",
    None,
    "Create or replace your event feedback",
    OBJECT,
    OBJECT,
    authentication="session",
)
def feedback_put(request, event_id):
    registration = _owned_registration(request, event_id)
    values = read_json_object(request)
    unknown = set(values) - {"rating", "comment", "would_change"}
    if unknown:
        raise APIError(400, "unknown_fields", "Feedback contains unsupported fields.")
    try:
        feedback, created = submit_feedback(registration, user=request.user, **values)
    except ValidationError as error:
        raise APIError(400, "feedback_unavailable", str(error)) from error
    return JsonResponse(
        {
            "feedback": {
                "rating": feedback.rating,
                "comment": feedback.comment,
                "would_change": feedback.would_change,
            }
        },
        status=201 if created else 200,
    )


@route(
    "GET",
    "events/<int:event_id>/registrations",
    None,
    "List event registrations for staff",
    COLLECTION,
    authentication="session",
)
def registrations_get(request, event_id):
    _staff(request)
    item = _event(event_id)
    return JsonResponse(
        {"results": [serialize_registration(row) for row in item.registrations.all()]}
    )


@route(
    "POST",
    "events/<int:event_id>/guest-invitations",
    None,
    "Invite an event guest",
    OBJECT,
    OBJECT,
    authentication="session",
)
def guest_invitation_post(request, event_id):
    _staff(request)
    values = read_json_object(request)
    if set(values) != {"email"}:
        raise APIError(400, "invalid_invitation", "Guest invitations require only an email.")
    try:
        result = invite_guest(_event(event_id), values["email"])
    except (TypeError, ValidationError) as error:
        raise APIError(400, "invalid_invitation", str(error)) from error
    return JsonResponse(
        {
            "registration": serialize_registration(result.registration),
            "delivery_id": str(result.delivery.pk),
        },
        status=201 if result.created else 200,
    )


@route(
    "GET", "event-series", None, "List event series for staff", COLLECTION, authentication="session"
)
def series_get(request):
    _staff(request)
    return JsonResponse({"results": [serialize_series(item) for item in EventSeries.objects.all()]})


@route(
    "POST", "event-series", None, "Create event series", OBJECT, OBJECT, authentication="session"
)
def series_post(request):
    _staff(request)
    return JsonResponse(
        {"event_series": serialize_series(_model_form(request, EventSeriesForm))}, status=201
    )


@route(
    "PATCH",
    "event-series/<int:series_id>",
    None,
    "Update event series",
    OBJECT,
    OBJECT,
    authentication="session",
)
def series_patch(request, series_id):
    _staff(request)
    item = _model_form(request, EventSeriesForm, instance=_series(series_id))
    return JsonResponse({"event_series": serialize_series(item)})


@route(
    "DELETE",
    "event-series/<int:series_id>",
    None,
    "Delete event series",
    OBJECT,
    authentication="session",
)
def series_delete(request, series_id):
    _staff(request)
    _series(series_id).delete()
    return JsonResponse({"status": "deleted"})


@route(
    "GET", "event-hosts", None, "List event hosts for staff", COLLECTION, authentication="session"
)
def hosts_get(request):
    _staff(request)
    return JsonResponse({"results": [serialize_host(item) for item in Host.objects.all()]})


@route("POST", "event-hosts", None, "Create event host", OBJECT, OBJECT, authentication="session")
def hosts_post(request):
    _staff(request)
    return JsonResponse({"host": serialize_host(_model_form(request, HostForm))}, status=201)


@route(
    "PATCH",
    "event-hosts/<int:host_id>",
    None,
    "Update event host",
    OBJECT,
    OBJECT,
    authentication="session",
)
def host_patch(request, host_id):
    _staff(request)
    return JsonResponse(
        {"host": serialize_host(_model_form(request, HostForm, instance=_host(host_id)))}
    )


@route(
    "DELETE",
    "event-hosts/<int:host_id>",
    None,
    "Delete event host",
    OBJECT,
    authentication="session",
)
def host_delete(request, host_id):
    _staff(request)
    try:
        _host(host_id).delete()
    except ProtectedError as error:
        raise APIError(409, "event_host_in_use", "Event host is still referenced.") from error
    return JsonResponse({"status": "deleted"})
