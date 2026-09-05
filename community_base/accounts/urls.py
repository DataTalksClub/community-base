from django.urls import include, path

from community_base.accounts import views
from community_base.accounts.account_page import account_view

urlpatterns = [
    path("account/", account_view, name="account"),
    path("login/", views.login_view, name="account_login"),
    path("logout/", views.logout_view, name="account_logout"),
    path("register/", views.register_view, name="account_register"),
    path("signup/", views.signup_redirect_view, name="account_signup"),
    path(
        "verification-sent/",
        views.verification_sent_view,
        name="account_verification_sent",
    ),
    path(
        "resend-verification",
        views.resend_verification_view,
        name="account_resend_verification",
    ),
    path("verify/", views.verify_email_view, name="account_verify_email"),
    path("verify-email", views.verify_email_view),
    path("password-reset/", views.password_reset_view, name="account_password_reset"),
    path(
        "password-reset-request",
        views.password_reset_request_view,
        name="account_password_reset_request",
    ),
    path("password-reset", views.password_reset_view),
    path(
        "password-reset/complete/",
        views.password_reset_complete_view,
        name="account_password_reset_complete",
    ),
    path("", include("allauth.urls")),
]

api_urlpatterns = [
    path("register", views.register_api, name="api_register"),
    path("login", views.login_api, name="api_login"),
    path("verify-email", views.verify_email_view, name="api_verify_email"),
    path("resend-verification", views.resend_verification_api, name="api_resend_verification"),
    path(
        "password-reset-request",
        views.password_reset_request_api,
        name="api_password_reset_request",
    ),
    path("password-reset", views.password_reset_api, name="api_password_reset"),
]
