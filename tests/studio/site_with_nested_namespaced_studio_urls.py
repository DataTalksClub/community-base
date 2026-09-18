"""The namespaced Studio mount nested inside a second namespace."""

from django.urls import include, path

inner = [
    path("studio/", include("tests.studio.studio_site_routes")),
]

urlpatterns = [
    path("ops/", include((inner, "ops"))),
]
