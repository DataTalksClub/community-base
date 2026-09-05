from django.urls import path

from community_base.questionnaires import studio_views

urlpatterns = [
    path("questionnaires/", studio_views.questionnaire_list, name="questionnaires_studio_list"),
    path(
        "questionnaires/new/",
        studio_views.questionnaire_create,
        name="questionnaires_studio_create",
    ),
    path(
        "questionnaires/<int:questionnaire_id>/",
        studio_views.questionnaire_detail,
        name="questionnaires_studio_detail",
    ),
    path(
        "questionnaires/<int:questionnaire_id>/edit/",
        studio_views.questionnaire_edit,
        name="questionnaires_studio_edit",
    ),
    path(
        "questionnaires/<int:questionnaire_id>/questions/new/",
        studio_views.question_create,
        name="questionnaires_studio_question_create",
    ),
    path(
        "questionnaires/<int:questionnaire_id>/questions/<int:question_id>/edit/",
        studio_views.question_edit,
        name="questionnaires_studio_question_edit",
    ),
    path(
        "questionnaires/<int:questionnaire_id>/questions/<int:question_id>/delete/",
        studio_views.question_delete,
        name="questionnaires_studio_question_delete",
    ),
    path("personas/", studio_views.persona_list, name="questionnaires_studio_persona_list"),
    path("personas/new/", studio_views.persona_create, name="questionnaires_studio_persona_create"),
    path(
        "personas/<int:persona_id>/edit/",
        studio_views.persona_edit,
        name="questionnaires_studio_persona_edit",
    ),
    path(
        "questionnaire-responses/",
        studio_views.response_queue,
        name="questionnaires_studio_response_queue",
    ),
    path(
        "questionnaires/<int:questionnaire_id>/responses/<int:response_id>/",
        studio_views.response_detail,
        name="questionnaires_studio_response_detail",
    ),
    path(
        "questionnaires/<int:questionnaire_id>/responses/<int:response_id>/review/",
        studio_views.response_review,
        name="questionnaires_studio_response_review",
    ),
    path(
        "questionnaires/<int:questionnaire_id>/responses/<int:response_id>/questions/new/",
        studio_views.response_question_create,
        name="questionnaires_studio_response_question_create",
    ),
    path(
        "questionnaires/<int:questionnaire_id>/responses/<int:response_id>/questions/<int:question_id>/edit/",
        studio_views.response_question_edit,
        name="questionnaires_studio_response_question_edit",
    ),
    path(
        "questionnaires/<int:questionnaire_id>/responses/<int:response_id>/questions/<int:question_id>/delete/",
        studio_views.response_question_delete,
        name="questionnaires_studio_response_question_delete",
    ),
]
