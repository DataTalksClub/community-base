from community_base.studio.registry import Destination, Section, register

EVENT_STUDIO_ROUTES = (
    "events_studio_list",
    "events_studio_create",
    "events_studio_detail",
    "events_studio_edit",
    "events_studio_delete",
    "events_studio_invite_guest",
    "events_studio_registration_state",
    "events_studio_series_list",
    "events_studio_series_create",
    "events_studio_series_edit",
    "events_studio_series_delete",
    "events_studio_host_list",
    "events_studio_host_create",
    "events_studio_host_edit",
    "events_studio_host_delete",
)


def register_studio():
    register(
        Section(
            slug="events",
            title="Events",
            order=50,
            icon="calendar",
            destinations=(
                Destination(
                    key="events",
                    title="Events",
                    url_name="events_studio_list",
                    route_names=EVENT_STUDIO_ROUTES,
                    order=10,
                ),
            ),
        )
    )
