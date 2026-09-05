from django.urls import path

from community_base.accounts import self_api

urlpatterns = [
    path("me", self_api.me, name="community_base_me"),
    path("me/profile", self_api.me_profile, name="community_base_me_profile"),
    path("me/password", self_api.me_password, name="community_base_me_password"),
    path("me/data-export", self_api.me_data_export, name="community_base_me_data_export"),
    path(
        "me/deletion-request",
        self_api.me_deletion_request,
        name="community_base_me_deletion_request",
    ),
]
