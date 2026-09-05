from community_base.studio.registry import Destination, Section, register


def register_studio():
    register(
        Section(
            slug="operations",
            title="Operations",
            order=80,
            icon="settings",
            destinations=(
                Destination(
                    key="content_sync",
                    title="Content sync",
                    url_name="community_base_content_sources",
                    route_names=(
                        "community_base_content_sources",
                        "community_base_content_source_edit",
                        "community_base_content_source_sync",
                        "community_base_content_sync_history",
                        "community_base_content_sync_worker",
                    ),
                    order=40,
                ),
            ),
        )
    )
