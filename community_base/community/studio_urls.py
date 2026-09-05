from django.urls import path

from community_base.community import studio_views

urlpatterns = [
    path("community/access/", studio_views.access_list, name="community_studio_access_list"),
    path("community/audit/", studio_views.audit_list, name="community_studio_audit_list"),
    path(
        "community/call-hosts/",
        studio_views.call_host_list,
        name="community_studio_call_host_list",
    ),
    path(
        "community/call-hosts/new/",
        studio_views.call_host_create,
        name="community_studio_call_host_create",
    ),
    path(
        "community/call-hosts/<int:host_id>/edit/",
        studio_views.call_host_edit,
        name="community_studio_call_host_edit",
    ),
    path(
        "community/booked-calls/",
        studio_views.booked_call_list,
        name="community_studio_booked_call_list",
    ),
    path(
        "community/unmatched-calls/",
        studio_views.unmatched_call_list,
        name="community_studio_unmatched_call_list",
    ),
]
