from django.urls import path

from community_base.events import views

urlpatterns = [
    path("", views.event_list, name="events_list"),
    path("registration/verify/", views.registration_verify, name="event_registration_verify"),
    path("registration/manage/", views.registration_manage, name="event_registration_manage"),
    path("<int:public_id>/<slug:slug>/register/", views.event_register, name="event_register"),
    path("<slug:slug>/register/", views.event_register, name="event_register"),
    path(
        "<int:public_id>/<slug:slug>/unregister/", views.event_unregister, name="event_unregister"
    ),
    path("<slug:slug>/unregister/", views.event_unregister, name="event_unregister"),
    path("<int:public_id>/<slug:slug>/feedback/", views.event_feedback, name="event_feedback"),
    path("<slug:slug>/feedback/", views.event_feedback, name="event_feedback"),
    path("<int:public_id>/<slug:slug>/calendar.ics", views.event_calendar, name="event_calendar"),
    path("<slug:slug>/calendar.ics", views.event_calendar, name="event_calendar"),
    path("<int:public_id>/<slug:slug>/", views.event_detail, name="event_detail"),
    path("<slug:slug>/", views.event_detail, name="event_detail"),
    path("<path:alias>/", views.event_alias, name="event_alias"),
]
