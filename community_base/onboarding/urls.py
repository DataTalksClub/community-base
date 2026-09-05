from django.urls import path

from community_base.onboarding import views

urlpatterns = [
    path("", views.start, name="community_base_onboarding_start"),
    path("resume/", views.resume, name="community_base_onboarding_resume"),
    path("step/", views.step, name="community_base_onboarding_step"),
    path("submit/", views.submit, name="community_base_onboarding_submit"),
    path("prompt/", views.dashboard_prompt, name="community_base_onboarding_prompt"),
]
