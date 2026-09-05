from community_base.studio.registry import Destination, Section, register

QUESTIONNAIRE_STUDIO_ROUTES = (
    "questionnaires_studio_list",
    "questionnaires_studio_create",
    "questionnaires_studio_detail",
    "questionnaires_studio_edit",
    "questionnaires_studio_question_create",
    "questionnaires_studio_question_edit",
    "questionnaires_studio_question_delete",
    "questionnaires_studio_question_reorder",
    "questionnaires_studio_option_reorder",
    "questionnaires_studio_persona_list",
    "questionnaires_studio_persona_create",
    "questionnaires_studio_persona_edit",
    "questionnaires_studio_persona_reorder",
    "questionnaires_studio_response_queue",
    "questionnaires_studio_responses",
    "questionnaires_studio_response_detail",
    "questionnaires_studio_response_review",
    "questionnaires_studio_response_question_create",
    "questionnaires_studio_response_question_edit",
    "questionnaires_studio_response_question_delete",
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
                    key="questionnaires",
                    title="Questionnaires",
                    url_name="questionnaires_studio_list",
                    route_names=QUESTIONNAIRE_STUDIO_ROUTES,
                    order=10,
                ),
            ),
        )
    )
