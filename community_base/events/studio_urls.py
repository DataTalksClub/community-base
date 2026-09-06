from django.urls import path

from community_base.events import studio_views

urlpatterns = [
    path("events/", studio_views.event_list, name="events_studio_list"),
    path("events/create/", studio_views.event_create, name="events_studio_create"),
    path("events/<int:event_id>/", studio_views.event_detail, name="events_studio_detail"),
    path("events/<int:event_id>/edit/", studio_views.event_edit, name="events_studio_edit"),
    path("events/<int:event_id>/delete/", studio_views.event_delete, name="events_studio_delete"),
    path(
        "events/<int:event_id>/invite/",
        studio_views.event_invite_guest,
        name="events_studio_invite_guest",
    ),
    path(
        "events/<int:event_id>/registrations/<uuid:registration_id>/state/",
        studio_views.registration_state,
        name="events_studio_registration_state",
    ),
    path("event-series/", studio_views.series_list, name="events_studio_series_list"),
    path("event-series/create/", studio_views.series_create, name="events_studio_series_create"),
    path(
        "event-series/<int:series_id>/edit/",
        studio_views.series_edit,
        name="events_studio_series_edit",
    ),
    path(
        "event-series/<int:series_id>/delete/",
        studio_views.series_delete,
        name="events_studio_series_delete",
    ),
    path("event-hosts/", studio_views.host_list, name="events_studio_host_list"),
    path("event-hosts/create/", studio_views.host_create, name="events_studio_host_create"),
    path(
        "event-hosts/<int:host_id>/edit/",
        studio_views.host_edit,
        name="events_studio_host_edit",
    ),
    path(
        "event-hosts/<int:host_id>/delete/",
        studio_views.host_delete,
        name="events_studio_host_delete",
    ),
]
