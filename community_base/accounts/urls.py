from django.urls import path

from community_base.accounts import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("register/", views.register_view, name="register"),
    path("verification-sent/", views.verification_sent_view, name="verification_sent"),
    path("verify/", views.verify_email_view, name="verify_email"),
    path("password-reset/", views.password_reset_view, name="password_reset"),
    path(
        "password-reset/request/", views.password_reset_request_view, name="password_reset_request"
    ),
    path(
        "password-reset/complete/",
        views.password_reset_complete_view,
        name="password_reset_complete",
    ),
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
