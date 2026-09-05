from django.urls import path

from community_base.mail import studio

urlpatterns = [
    path("mail/", studio.deliveries_list, name="community_base_mail_deliveries"),
    path(
        "mail/<uuid:delivery_id>/",
        studio.delivery_detail,
        name="community_base_mail_delivery",
    ),
]
