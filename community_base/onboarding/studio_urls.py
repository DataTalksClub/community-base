from django.urls import path

from community_base.onboarding import studio_views

urlpatterns = [
    path("onboarding/flows/", studio_views.flow_list, name="onboarding_studio_flow_list"),
    path("onboarding/flows/new/", studio_views.flow_create, name="onboarding_studio_flow_create"),
    path(
        "onboarding/flows/<int:flow_id>/",
        studio_views.flow_detail,
        name="onboarding_studio_flow_detail",
    ),
    path(
        "onboarding/flows/<int:flow_id>/edit/",
        studio_views.flow_edit,
        name="onboarding_studio_flow_edit",
    ),
    path(
        "onboarding/flows/<int:flow_id>/steps/new/",
        studio_views.step_create,
        name="onboarding_studio_step_create",
    ),
    path(
        "onboarding/flows/<int:flow_id>/steps/<int:step_id>/edit/",
        studio_views.step_edit,
        name="onboarding_studio_step_edit",
    ),
    path(
        "onboarding/flows/<int:flow_id>/steps/<int:step_id>/delete/",
        studio_views.step_delete,
        name="onboarding_studio_step_delete",
    ),
    path(
        "onboarding/flows/<int:flow_id>/assignments/new/",
        studio_views.assignment_create,
        name="onboarding_studio_assignment_create",
    ),
    path(
        "onboarding/flows/<int:flow_id>/assignments/<int:assignment_id>/delete/",
        studio_views.assignment_delete,
        name="onboarding_studio_assignment_delete",
    ),
    path(
        "onboarding/progress/",
        studio_views.progress_list,
        name="onboarding_studio_progress_list",
    ),
]
