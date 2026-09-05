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
                    key="mail",
                    title="Mail",
                    url_name="community_base_mail_deliveries",
                    route_names=(
                        "community_base_mail_deliveries",
                        "community_base_mail_delivery",
                        "community_base_mail_templates",
                        "community_base_mail_template",
                    ),
                    order=40,
                ),
            ),
        )
    )
