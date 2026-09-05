from django.urls import path

from community_base.accounts import self_api

urlpatterns = [
    path("me", self_api.me, name="community_base_me"),
    path("me/profile", self_api.me_profile, name="community_base_me_profile"),
]
