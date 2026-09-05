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
                    key="api_keys",
                    title="API keys",
                    url_name="community_base_api_keys",
                    route_names=("community_base_api_keys", "community_base_api_key_revoke"),
                    order=20,
                    superuser_only=True,
                ),
            ),
        )
    )
