"""The same synthetic Studio routes mounted without a namespace."""

from django.urls import include, path

from tests.studio.studio_site_routes import urlpatterns as studio_urlpatterns

urlpatterns = [
    path("studio/", include("community_base.studio.urls")),
    path("studio/", include(studio_urlpatterns)),
]
