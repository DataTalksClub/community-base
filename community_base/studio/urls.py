from django.urls import path

from community_base.studio import impersonation, views

urlpatterns = [
    path("", views.dashboard, name="studio_dashboard"),
    path("search/", views.global_search, name="studio_global_search"),
    path("impersonate/<int:user_id>/", impersonation.start, name="studio_impersonate"),
    path("impersonate/stop/", impersonation.stop, name="studio_stop_impersonate"),
]
