from community_base.studio.registry import Destination, Section, register


def register_studio() -> None:
    register(
        Section(
            slug="operations",
            title="Operations",
            order=80,
            icon="settings",
            destinations=(
                Destination(
                    key="settings",
                    title="Settings",
                    url_name="community_base_settings",
                    route_names=(
                        "community_base_settings",
                        "community_base_settings_save_group",
                        "community_base_settings_export",
                        "community_base_settings_import",
                    ),
                    order=10,
                ),
            ),
        )
    )
