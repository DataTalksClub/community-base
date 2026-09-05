from django.urls import path

from community_base.comments import studio_views

urlpatterns = [
    path("comments/", studio_views.comment_list, name="comments_studio_list"),
    path(
        "comments/<int:comment_id>/moderate/",
        studio_views.comment_moderate,
        name="comments_studio_moderate",
    ),
]
