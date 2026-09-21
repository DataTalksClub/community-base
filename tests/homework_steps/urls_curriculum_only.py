from django.urls import path

from community_base.curriculum import views

urlpatterns = [path("courses/", views.course_catalog, name="course_catalog")]
