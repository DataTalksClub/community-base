from community_base.studio.registry import (
    Destination,
    Section,
    register,
    routes_without_home,
    sections,
)


def register_builtin_section() -> None:
    routes_without_home.update(
        {"studio_global_search", "studio_impersonate", "studio_stop_impersonate"}
    )
    registered_destinations = {
        destination.key for section in sections() for destination in section.destinations
    }
    if "dashboard" not in registered_destinations:
        register(
            Section(
                slug="home",
                title="",
                order=0,
                icon="layout-dashboard",
                destinations=(
                    Destination(
                        key="dashboard",
                        title="Dashboard",
                        url_name="studio_dashboard",
                        route_names=("studio_dashboard",),
                        order=0,
                    ),
                ),
            )
        )
    if "users" not in registered_destinations:
        register(
            Section(
                slug="people",
                title="People",
                order=30,
                icon="users",
                destinations=(
                    Destination(
                        key="users",
                        title="Users",
                        url_name="studio_user_list",
                        route_names=(
                            "studio_user_list",
                            "studio_user_export",
                            "studio_user_detail",
                            "studio_user_tag_add",
                            "studio_user_tag_remove",
                            "studio_member_note_create",
                            "studio_member_note_edit",
                            "studio_member_note_delete",
                        ),
                        order=10,
                    ),
                ),
            )
        )
