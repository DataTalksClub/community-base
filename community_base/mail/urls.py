from django.urls import path

from community_base.mail import views
from community_base.mail.callback_ingress import receive_callback

urlpatterns = [
    path("internal/mail/callback", receive_callback, name="relay-mail-callback"),
    path("t/o/<str:tracking_token>.gif", views.tracking_open, name="relay-tracking-open"),
    path("t/c/<str:tracking_token>", views.tracking_click, name="relay-tracking-click"),
    path(
        "unsubscribe/<str:unsubscribe_token>",
        views.public_unsubscribe,
        name="relay-public-unsubscribe",
    ),
]
