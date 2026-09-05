from django.urls import path

from community_base.studio import impersonation, user_views, views

urlpatterns = [
    path("", views.dashboard, name="studio_dashboard"),
    path("search/", views.global_search, name="studio_global_search"),
    path("impersonate/<int:user_id>/", impersonation.start, name="studio_impersonate"),
    path("impersonate/stop/", impersonation.stop, name="studio_stop_impersonate"),
    path("users/", user_views.user_list, name="studio_user_list"),
    path("users/export/", user_views.user_export, name="studio_user_export"),
    path("users/<int:user_id>/", user_views.user_detail, name="studio_user_detail"),
    path("users/<int:user_id>/tags/add/", user_views.user_tag_add, name="studio_user_tag_add"),
    path(
        "users/<int:user_id>/tags/<slug:tag>/remove/",
        user_views.user_tag_remove,
        name="studio_user_tag_remove",
    ),
    path("users/<int:user_id>/notes/", user_views.note_create, name="studio_member_note_create"),
    path(
        "users/<int:user_id>/notes/<int:note_id>/",
        user_views.note_edit,
        name="studio_member_note_edit",
    ),
    path(
        "users/<int:user_id>/notes/<int:note_id>/delete/",
        user_views.note_delete,
        name="studio_member_note_delete",
    ),
]
