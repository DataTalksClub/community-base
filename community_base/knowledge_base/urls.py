from django.urls import path

from community_base.knowledge_base import views

app_name = "knowledge_base"

urlpatterns = [
    path("wiki/", views.wiki_home, name="wiki_home"),
    # ``str`` rather than ``slug``: the donor slug alphabets carry dots.
    path("wiki/<str:slug>/", views.wiki_page, name="wiki_page"),
    path("docs/", views.docs_home, name="docs_home"),
    path("docs/<path:page_path>/", views.docs_page, name="docs_page"),
]
