from community_base.studio.registry import Destination, Section, register

ACCOUNT_STUDIO_ROUTES = (
    "accounts_studio_operations",
    "accounts_studio_user_create",
    "accounts_studio_user_import",
    "accounts_studio_import_detail",
    "accounts_studio_user_merge",
    "accounts_studio_privacy_detail",
    "accounts_studio_email_change_detail",
)


def register_studio():
    register(
        Section(
            slug="people",
            title="People",
            order=30,
            icon="users",
            destinations=(
                Destination(
                    key="account-operations",
                    title="Account operations",
                    url_name="accounts_studio_operations",
                    route_names=ACCOUNT_STUDIO_ROUTES,
                    order=20,
                ),
            ),
        )
    )
