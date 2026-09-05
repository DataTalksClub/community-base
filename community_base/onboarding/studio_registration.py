from community_base.studio.registry import Destination, Section, register

ROUTES = (
    "onboarding_studio_flow_list",
    "onboarding_studio_flow_create",
    "onboarding_studio_flow_detail",
    "onboarding_studio_flow_edit",
    "onboarding_studio_step_create",
    "onboarding_studio_step_edit",
    "onboarding_studio_step_delete",
    "onboarding_studio_assignment_create",
    "onboarding_studio_assignment_delete",
    "onboarding_studio_progress_list",
)


def register_studio():
    register(
        Section(
            slug="onboarding",
            title="Onboarding",
            order=40,
            icon="clipboard-list",
            destinations=(
                Destination(
                    key="onboarding-flows",
                    title="Flows",
                    url_name="onboarding_studio_flow_list",
                    route_names=ROUTES,
                    order=20,
                ),
            ),
        )
    )
