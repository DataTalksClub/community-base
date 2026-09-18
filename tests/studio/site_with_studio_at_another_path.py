"""A synthetic site that mounts the Studio somewhere other than `studio/`.

Nothing in Django reserves the path, and the package's own test project mounts at
`studio/` only because the one adopting site does.
"""

from django.urls import include, path

urlpatterns = [
    path("manage/", include("community_base.studio.urls")),
    path("manage/", include("community_base.jobs.studio_urls")),
]
