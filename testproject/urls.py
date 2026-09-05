from django.contrib import admin
from django.urls import include, path

from community_base.accounts.urls import api_urlpatterns as accounts_api_urlpatterns
from community_base.api import fixture_views  # noqa: F401
from community_base.api.registry import urlpatterns as api_urlpatterns
from community_base.notifications.urls import api_urlpatterns as notifications_api_urlpatterns

urlpatterns = [
    path("accounts/", include("community_base.accounts.urls")),
    path("questionnaires/", include("community_base.questionnaires.urls")),
    path("onboarding/", include("community_base.onboarding.urls")),
    path("", include("community_base.notifications.urls")),
    path("", include("community_base.comments.urls")),
    path("", include("community_base.voting.urls")),
    path("events/", include("community_base.events.urls")),
    path("accounts/community/", include("community_base.community.urls")),
    path("api/", include((accounts_api_urlpatterns, "accounts_api"))),
    path("api/", include(notifications_api_urlpatterns)),
    path("", include("community_base.mail.urls")),
    path("content-sync/", include("community_base.content_sync.urls")),
    path("admin/", admin.site.urls),
    path("api/v1/", include((api_urlpatterns(), "cb_api"))),
    path("internal/jobs/", include("community_base.jobs.urls")),
    path("studio/", include("community_base.studio.urls")),
    path("studio/", include("community_base.accounts.studio_urls")),
    path("studio/", include("community_base.questionnaires.studio_urls")),
    path("studio/", include("community_base.onboarding.studio_urls")),
    path("studio/", include("community_base.community.studio_urls")),
    path("studio/", include("community_base.comments.studio_urls")),
    path("studio/", include("community_base.jobs.studio_urls")),
    path("studio/", include("community_base.mail.studio_urls")),
    path("studio/", include("community_base.content_sync.studio_urls")),
    path("studio/", include("community_base.api.urls")),
    path("studio/", include("community_base.config.urls")),
]
