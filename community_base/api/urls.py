from django.urls import path

from community_base.api import views

urlpatterns = [
    path("api-keys/", views.api_keys, name="community_base_api_keys"),
    path(
        "api-keys/<str:key_id>/revoke/",
        views.revoke_api_key,
        name="community_base_api_key_revoke",
    ),
]
