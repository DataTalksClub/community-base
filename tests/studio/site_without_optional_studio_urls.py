"""A synthetic site: package apps installed, only the core Studio URLs mounted."""

from django.urls import include, path

urlpatterns = [
    path("studio/", include("community_base.studio.urls")),
]
