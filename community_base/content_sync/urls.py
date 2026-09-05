from django.urls import path

from community_base.content_sync.webhooks import github_webhook

app_name = "cb_content_sync"
urlpatterns = [path("github/webhook/", github_webhook, name="github_webhook")]
