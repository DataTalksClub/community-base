from community_base.studio.registry import Destination, Section, register

HOMEWORK_ROUTES = (
    "coursework_studio_homework_list",
    "coursework_studio_homework_create",
    "coursework_studio_homework_detail",
    "coursework_studio_homework_edit",
    "coursework_studio_homework_rescore",
    "coursework_studio_question_create",
    "coursework_studio_question_edit",
    "coursework_studio_question_delete",
)
PROJECT_ROUTES = (
    "coursework_studio_project_list",
    "coursework_studio_project_detail",
    "coursework_studio_project_assign_reviews",
    "coursework_studio_project_score",
    "coursework_studio_criteria_add",
    "coursework_studio_criteria_remove",
    "coursework_studio_volunteer_review_add",
    "coursework_studio_volunteer_review_remove",
)
OPERATIONS_ROUTES = (
    "coursework_studio_cohort_leaderboard",
    "coursework_studio_leaderboard_recompute",
    "coursework_studio_complaints",
    "coursework_studio_complaint_resolve",
    "coursework_studio_complaint_create",
    "coursework_studio_certificates",
    "coursework_studio_certificate_issue",
    "coursework_studio_campaigns",
    "coursework_studio_wrapped",
    "coursework_studio_wrapped_recalculate",
)


def register_studio():
    register(
        Section(
            slug="coursework",
            title="Coursework",
            order=36,
            icon="graduation-cap",
            destinations=(
                Destination(
                    key="homework",
                    title="Homework",
                    url_name="coursework_studio_homework_list",
                    route_names=HOMEWORK_ROUTES,
                    order=10,
                ),
                Destination(
                    key="projects",
                    title="Projects",
                    url_name="coursework_studio_project_list",
                    route_names=PROJECT_ROUTES,
                    order=20,
                ),
                Destination(
                    key="operations",
                    title="Operations",
                    url_name="coursework_studio_complaints",
                    route_names=OPERATIONS_ROUTES,
                    order=30,
                ),
            ),
        )
    )
