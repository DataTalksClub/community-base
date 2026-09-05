from django.urls import path

from community_base.mail import views

urlpatterns = [
    path("t/o/<str:tracking_token>.gif", views.tracking_open, name="relay-tracking-open"),
    path("t/c/<str:tracking_token>", views.tracking_click, name="relay-tracking-click"),
    path(
        "unsubscribe/<str:unsubscribe_token>",
        views.public_unsubscribe,
        name="relay-public-unsubscribe",
    ),
]
