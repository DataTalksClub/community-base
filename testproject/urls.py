from django.contrib import admin
from django.urls import include, path

from community_base.api import fixture_views  # noqa: F401
from community_base.api.registry import urlpatterns as api_urlpatterns

urlpatterns = [
    path("", include("community_base.mail.urls")),
    path("admin/", admin.site.urls),
    path("api/v1/", include((api_urlpatterns(), "cb_api"))),
    path("internal/jobs/", include("community_base.jobs.urls")),
    path("studio/", include("community_base.studio.urls")),
    path("studio/", include("community_base.jobs.studio_urls")),
    path("studio/", include("community_base.mail.studio_urls")),
    path("studio/", include("community_base.api.urls")),
    path("studio/", include("community_base.config.urls")),
]
