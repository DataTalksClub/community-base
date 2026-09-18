"""A site Studio URL module shaped like the DataTalks.Club one, with `app_name`.

Mounted through `include("tests.studio.studio_site_routes")` the routes live
under the `studio` namespace, so they resolve and reverse as `studio:settings`.
Mounted through `include(urlpatterns)` the same routes carry no namespace, which
is how AI Shipping Labs mounts Studio. The two mounts share this module so the
namespaced and namespace-free cases differ in exactly one thing.
"""

from django.http import HttpResponse
from django.urls import path

app_name = "studio"


def page(request, **kwargs):
    return HttpResponse("studio page")


urlpatterns = [
    path("", page, name="home"),
    path("settings/", page, name="settings"),
    path("audit/", page, name="audit-list"),
    path("audit/<int:event_id>/", page, name="audit-detail"),
    path("unnamed/", page),
]
