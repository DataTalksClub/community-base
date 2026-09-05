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
                    key="jobs",
                    title="Jobs",
                    url_name="community_base_jobs",
                    route_names=(
                        "community_base_jobs",
                        "community_base_job_retry",
                        "community_base_job_discard",
                    ),
                    order=30,
                ),
            ),
        )
    )
