"""Learner coursework routes, mounted by each site under its courses prefix.

The package fixes the view signatures and URL names (prefixed
``coursework_``); the concrete paths stay with each site's urlconf. The
patterns below carry the donor's two-segment canonical form
(``<slug:course_slug>/<slug:cohort_identifier>/...``); sites may alias the
shorter cohort-less forms to the same views the way the donor's
``courses/urls.py`` does.
"""

from django.urls import path

from community_base.coursework import views

urlpatterns = [
    path(
        "<slug:course_slug>/<slug:cohort_identifier>/homework/<slug:homework_slug>/",
        views.homework_view,
        name="coursework_homework",
    ),
    path(
        "<slug:course_slug>/<slug:cohort_identifier>/project/<slug:project_slug>/",
        views.project_view,
        name="coursework_project",
    ),
    path(
        "<slug:course_slug>/<slug:cohort_identifier>/project/<slug:project_slug>/eval/",
        views.projects_eval_view,
        name="coursework_projects_eval",
    ),
    path(
        "<slug:course_slug>/<slug:cohort_identifier>/project/<slug:project_slug>/eval/<int:review_id>/",
        views.projects_eval_submit,
        name="coursework_projects_eval_submit",
    ),
    path(
        "<slug:course_slug>/<slug:cohort_identifier>/project/<slug:project_slug>/eval/add/<int:submission_id>/",
        views.projects_eval_add,
        name="coursework_projects_eval_add",
    ),
    path(
        "<slug:course_slug>/<slug:cohort_identifier>/project/<slug:project_slug>/eval/delete/<int:review_id>/",
        views.projects_eval_delete,
        name="coursework_projects_eval_delete",
    ),
    path(
        "<slug:course_slug>/<slug:cohort_identifier>/leaderboard/",
        views.leaderboard_view,
        name="coursework_leaderboard",
    ),
    path(
        "<slug:course_slug>/<slug:cohort_identifier>/leaderboard/<int:enrollment_id>/",
        views.leaderboard_score_breakdown_view,
        name="coursework_leaderboard_score_breakdown",
    ),
    path(
        "<slug:course_slug>/<slug:cohort_identifier>/leaderboard/data/",
        views.leaderboard_data_view,
        name="coursework_leaderboard_data",
    ),
    path(
        "<slug:course_slug>/<slug:cohort_identifier>/leaderboard/<int:enrollment_id>/report/",
        views.leaderboard_complaint_view,
        name="coursework_leaderboard_complaint",
    ),
    path(
        "<slug:course_slug>/<slug:cohort_identifier>/enrollment/toggle/",
        views.enrollment_preferences_toggle,
        name="coursework_enrollment_toggle",
    ),
    path(
        "<slug:course_slug>/<slug:cohort_identifier>/certificate/",
        views.certificate_view,
        name="coursework_certificate",
    ),
]
