"""A synthetic site that mounts a namespaced Studio somewhere other than `studio/`.

Both adoption shapes at once: DataTalks.Club's Studio URL module declares
`app_name`, and nothing reserves the `studio/` path. `site_with_studio_at_another_path`
covers the mount path alone; this one adds the namespace, which is the
combination the package has to serve for a site to adopt the shell.

One namespace covers both mounted modules, the way a site that namespaces its
Studio would write it, rather than repeating the instance namespace per include.
"""

from django.urls import include, path

studio_patterns = [
    path("", include("community_base.studio.urls")),
    path("", include("community_base.jobs.studio_urls")),
]

urlpatterns = [
    path("manage/", include((studio_patterns, "studio"))),
]
