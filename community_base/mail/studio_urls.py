from django.urls import path

from community_base.mail import catalog_studio, studio

urlpatterns = [
    path(
        "mail/templates/",
        catalog_studio.template_list,
        name="community_base_mail_templates",
    ),
    path(
        "mail/templates/<str:template_key>/",
        catalog_studio.template_detail,
        name="community_base_mail_template",
    ),
    path("mail/", studio.deliveries_list, name="community_base_mail_deliveries"),
    path(
        "mail/<uuid:delivery_id>/",
        studio.delivery_detail,
        name="community_base_mail_delivery",
    ),
]
