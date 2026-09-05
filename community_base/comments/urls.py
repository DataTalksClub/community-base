from django.urls import path

from community_base.comments import views

urlpatterns = [
    path(
        "api/comments/<uuid:content_id>",
        views.comments_endpoint,
        name="comments_endpoint",
    ),
    path(
        "api/comments/<int:comment_id>/reply",
        views.reply_to_comment,
        name="comments_reply",
    ),
    path(
        "api/comments/<int:comment_id>/vote",
        views.toggle_vote,
        name="comments_vote",
    ),
]
