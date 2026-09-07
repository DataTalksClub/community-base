from django.urls import path

from community_base.curriculum import views

urlpatterns = [
    path("api/courses/", views.api_courses, name="curriculum_api_courses"),
    path(
        "api/courses/<slug:course_slug>/",
        views.api_course_detail,
        name="curriculum_api_course_detail",
    ),
    path(
        "<slug:course_slug>/units/<int:unit_id>/complete/",
        views.api_unit_complete,
        name="curriculum_api_unit_complete",
    ),
    path(
        "<slug:course_slug>/units/<int:unit_id>/",
        views.api_unit_detail,
        name="curriculum_api_unit_detail",
    ),
    path("", views.course_catalog, name="curriculum_course_catalog"),
    path("<slug:course_slug>/", views.course_detail, name="curriculum_course_detail"),
    path("<slug:course_slug>/enroll/", views.course_enroll, name="curriculum_course_enroll"),
    path("<slug:course_slug>/unenroll/", views.course_unenroll, name="curriculum_course_unenroll"),
    path(
        "<slug:course_slug>/cohorts/<slug:cohort_slug>/enroll/",
        views.cohort_enroll,
        name="curriculum_cohort_enroll",
    ),
    path(
        "<slug:course_slug>/cohorts/<slug:cohort_slug>/unenroll/",
        views.cohort_unenroll,
        name="curriculum_cohort_unenroll",
    ),
    path(
        "<slug:course_slug>/<slug:cohort_slug>/<slug:module_slug>/",
        views.module_overview,
        name="curriculum_module_overview",
    ),
    path(
        "<slug:course_slug>/<slug:cohort_slug>/<slug:module_slug>/<slug:unit_slug>/",
        views.unit_detail,
        name="curriculum_unit_detail",
    ),
]
