"""The same synthetic site with the mail and knowledge base Studio URLs mounted."""

from django.urls import include, path

urlpatterns = [
    path("studio/", include("community_base.studio.urls")),
    path("studio/", include("community_base.mail.studio_urls")),
    path("studio/", include("community_base.knowledge_base.studio_urls")),
]
