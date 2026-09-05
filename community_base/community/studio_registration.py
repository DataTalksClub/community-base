from community_base.studio.registry import Destination, Section, register


def register_studio():
    register(
        Section(
            slug="community",
            title="Community",
            icon="users",
            order=45,
            destinations=(
                Destination(
                    key="community-access",
                    title="Slack access",
                    url_name="community_studio_access_list",
                    route_names=("community_studio_access_list",),
                    order=10,
                ),
                Destination(
                    key="community-audit",
                    title="Audit log",
                    url_name="community_studio_audit_list",
                    route_names=("community_studio_audit_list",),
                    order=20,
                ),
                Destination(
                    key="community-call-hosts",
                    title="Call hosts",
                    url_name="community_studio_call_host_list",
                    route_names=(
                        "community_studio_call_host_list",
                        "community_studio_call_host_create",
                        "community_studio_call_host_edit",
                    ),
                    order=30,
                ),
                Destination(
                    key="community-booked-calls",
                    title="Booked calls",
                    url_name="community_studio_booked_call_list",
                    route_names=(
                        "community_studio_booked_call_list",
                        "community_studio_unmatched_call_list",
                    ),
                    order=40,
                ),
            ),
        )
    )
