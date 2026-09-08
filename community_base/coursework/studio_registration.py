from community_base.studio.registry import Destination, Section, register

COURSEWORK_STUDIO_ROUTES = (
    "coursework_studio_cohort_list",
    "coursework_studio_cohort",
    "coursework_studio_homework_score",
    "coursework_studio_homework_rescore",
    "coursework_studio_homework_extend_deadline",
    "coursework_studio_homework_save_answers",
    "coursework_studio_homework_set_correct_answers",
    "coursework_studio_homework_clear_correct_answers",
    "coursework_studio_homework_submissions",
    "coursework_studio_homework_submission_edit",
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
                    key="coursework",
                    title="Coursework",
                    url_name="coursework_studio_cohort_list",
                    route_names=COURSEWORK_STUDIO_ROUTES,
                    order=10,
                ),
            ),
        )
    )
