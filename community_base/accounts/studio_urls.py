from django.urls import path

from community_base.accounts import studio_views

urlpatterns = [
    path("account-operations/", studio_views.account_operations, name="accounts_studio_operations"),
    path("users/create/", studio_views.user_create, name="accounts_studio_user_create"),
    path("users/import/", studio_views.user_import, name="accounts_studio_user_import"),
    path(
        "users/import/<int:batch_id>/",
        studio_views.import_detail,
        name="accounts_studio_import_detail",
    ),
    path("users/merge/", studio_views.user_merge, name="accounts_studio_user_merge"),
    path(
        "account-operations/privacy/<int:request_id>/",
        studio_views.privacy_request_detail,
        name="accounts_studio_privacy_detail",
    ),
    path(
        "account-operations/email-change/<int:change_id>/",
        studio_views.email_change_detail,
        name="accounts_studio_email_change_detail",
    ),
]
