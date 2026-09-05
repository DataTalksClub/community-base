from django.urls import path

from community_base.config import views

urlpatterns = [
    path("settings/", views.settings_list, name="community_base_settings"),
    path(
        "settings/<str:group>/save/",
        views.settings_save_group,
        name="community_base_settings_save_group",
    ),
    path("settings/export/", views.settings_export, name="community_base_settings_export"),
    path("settings/import/", views.settings_import, name="community_base_settings_import"),
]
