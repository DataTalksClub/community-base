from django.urls import path

from community_base.community import views

urlpatterns = [
    path("slack/", views.slack_access, name="community_base_slack_access"),
    path("calendly/webhook/", views.calendly_webhook, name="community_base_calendly_webhook"),
]
