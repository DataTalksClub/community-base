from django.urls import path

from community_base.notifications import views

api_urlpatterns = [
    path("notifications", views.api_notification_list, name="api_notification_list"),
    path("notifications/unread-count", views.api_unread_count, name="api_unread_count"),
    path(
        "notifications/<int:notification_id>/read",
        views.api_mark_read,
        name="api_mark_read",
    ),
    path("notifications/read-all", views.api_mark_all_read, name="api_mark_all_read"),
]

page_urlpatterns = [
    path("notifications", views.notification_list_page, name="notification_list"),
]

urlpatterns = page_urlpatterns
