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
                    key="comments",
                    title="Comments",
                    url_name="comments_studio_list",
                    route_names=("comments_studio_list", "comments_studio_moderate"),
                    order=50,
                ),
            ),
        )
    )
