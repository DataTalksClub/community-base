"""A synthetic site whose Studio URL module declares an application namespace.

The package Studio shell mounts alongside it without a namespace, the way a
site that adopts the shell keeps its own Studio routes: the mounted names are a
mix of `studio_dashboard` and `studio:settings`.
"""

from django.urls import include, path

urlpatterns = [
    path("studio/", include("community_base.studio.urls")),
    path("studio/", include("tests.studio.studio_site_routes")),
]
