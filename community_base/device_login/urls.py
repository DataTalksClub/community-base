from django.urls import path

from community_base.device_login import views

# All device routes are slashless: consuming sites strip trailing slashes
# (and 301 a POST into a GET), so a trailing slash here would break the CLI.
urlpatterns = [
    path("device", views.device_page, name="community_device_login_page"),
    path("api/auth/device", views.device_start, name="community_device_login_start"),
    path("api/auth/device/token", views.device_token, name="community_device_login_token"),
    path(
        "api/auth/device/pending",
        views.device_pending,
        name="community_device_login_pending",
    ),
    path(
        "api/auth/device/approve",
        views.device_approve,
        name="community_device_login_approve",
    ),
]
