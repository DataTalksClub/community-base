"""Studio routes for the coursework app, mounted by each site under /studio/."""

from django.urls import path

from community_base.coursework import studio_views

urlpatterns = [
    path("coursework/", studio_views.cohort_list, name="coursework_studio_cohort_list"),
    path(
        "coursework/<int:cohort_id>/",
        studio_views.cohort_admin,
        name="coursework_studio_cohort",
    ),
    path(
        "coursework/homework/<int:homework_id>/score/",
        studio_views.homework_score,
        name="coursework_studio_homework_score",
    ),
    path(
        "coursework/homework/<int:homework_id>/rescore/",
        studio_views.homework_rescore,
        name="coursework_studio_homework_rescore",
    ),
    path(
        "coursework/homework/<int:homework_id>/extend-deadline/",
        studio_views.homework_extend_deadline,
        name="coursework_studio_homework_extend_deadline",
    ),
    path(
        "coursework/homework/<int:homework_id>/save-answers/",
        studio_views.homework_save_answers,
        name="coursework_studio_homework_save_answers",
    ),
    path(
        "coursework/homework/<int:homework_id>/set-correct-answers/",
        studio_views.homework_set_correct_answers,
        name="coursework_studio_homework_set_correct_answers",
    ),
    path(
        "coursework/homework/<int:homework_id>/clear-correct-answers/",
        studio_views.homework_clear_correct_answers,
        name="coursework_studio_homework_clear_correct_answers",
    ),
    path(
        "coursework/homework/<int:homework_id>/submissions/",
        studio_views.homework_submissions,
        name="coursework_studio_homework_submissions",
    ),
    path(
        "coursework/homework/<int:homework_id>/submissions/<int:submission_id>/edit/",
        studio_views.homework_submission_edit,
        name="coursework_studio_homework_submission_edit",
    ),
]
