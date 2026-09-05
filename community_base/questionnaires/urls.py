from django.urls import path

from community_base.questionnaires import ai_views

urlpatterns = [
    path("ai/", ai_views.chat, name="questionnaires_ai_chat"),
    path("ai/message/", ai_views.message, name="questionnaires_ai_message"),
    path("ai/stream/", ai_views.stream, name="questionnaires_ai_stream"),
]
