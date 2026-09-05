from django.urls import path

from community_base.voting import views

urlpatterns = [
    path("vote", views.poll_list, name="poll_list"),
    path("vote/<uuid:poll_id>", views.poll_detail, name="poll_detail"),
    path("api/vote/<uuid:poll_id>/vote", views.vote_toggle, name="vote_toggle"),
    path("api/vote/<uuid:poll_id>/propose", views.propose_option, name="propose_option"),
]
