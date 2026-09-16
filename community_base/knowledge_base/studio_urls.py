from django.urls import path

from community_base.knowledge_base import studio_views

urlpatterns = [
    path("knowledge-base/", studio_views.page_list, name="knowledge_base_studio_page_list"),
    path(
        "knowledge-base/<int:page_id>/",
        studio_views.page_detail,
        name="knowledge_base_studio_page_detail",
    ),
]
