import csv
from io import StringIO

import pytest
from django.urls import reverse

from community_base.studio.models import MemberNote
from community_base.studio.user_registry import (
    register_user_badge,
    register_user_column,
    register_user_panel,
)
from community_base.studio.user_tags import get_tags, set_tags

pytestmark = pytest.mark.django_db


@pytest.fixture
def operator(django_user_model):
    return django_user_model.objects.create_user(username="operator", is_staff=True)


def test_user_list_paginates_sixty_users_at_twenty_five(client, django_user_model, operator):
    django_user_model.objects.bulk_create(
        [django_user_model(username=f"member-{index:02d}") for index in range(59)]
    )
    client.force_login(operator)

    response = client.get(reverse("studio_user_list"))

    assert response.status_code == 200
    assert response.context["filtered_total"] == 60
    assert len(response.context["rows"]) == 25
    assert response.context["paginator"].num_pages == 3


def test_user_list_combines_search_status_and_tag_filters(client, django_user_model, operator):
    matching = django_user_model.objects.create_user(username="ada-active", email="ada@example.com")
    django_user_model.objects.create_user(username="ada-disabled", is_active=False)
    set_tags(matching, ["Early Adopter"])
    client.force_login(operator)

    response = client.get(
        reverse("studio_user_list"),
        {"q": "ada", "status": "active", "tag": "early adopter"},
    )

    assert [row["user"] for row in response.context["rows"]] == [matching]
    assert response.context["tag"] == "early-adopter"


def test_csv_export_uses_filters_and_extension_columns(client, django_user_model, operator):
    member = django_user_model.objects.create_user(username="export-me", email="export@example.com")
    set_tags(member, ["speaker"])
    register_user_column("identity", "Identity", lambda user: f"id-{user.pk}")
    client.force_login(operator)

    response = client.get(reverse("studio_user_export"), {"q": "export-me"})
    rows = list(csv.reader(StringIO(response.content.decode())))

    assert response["Content-Type"] == "text/csv"
    assert rows[0][-1] == "identity"
    assert rows[1][1:5] == ["export-me", "export@example.com", "active", "speaker"]
    assert rows[1][-1] == f"id-{member.pk}"


def test_detail_aggregates_badges_and_registered_panels(client, django_user_model, operator):
    member = django_user_model.objects.create_user(username="panel-user")
    register_user_badge(lambda user: {"label": "Example badge", "classes": "example"})
    register_user_panel(
        "Example panel",
        "test_user_panel.html",
        lambda request, user: {"message": "Hello"},
    )
    client.force_login(operator)

    response = client.get(reverse("studio_user_detail", args=(member.pk,)))

    assert response.status_code == 200
    assert b"Example badge" in response.content
    assert b"Example panel" in response.content
    assert b"Hello for panel-user" in response.content


def test_tag_add_and_remove_use_configured_accessor(client, django_user_model, operator):
    member = django_user_model.objects.create_user(username="tagged-user")
    client.force_login(operator)

    client.post(reverse("studio_user_tag_add", args=(member.pk,)), {"tag": "Early Adopter"})
    assert get_tags(member) == ["early-adopter"]

    client.post(reverse("studio_user_tag_remove", args=(member.pk, "early-adopter")))
    assert get_tags(member) == []


def test_member_note_create_edit_delete(client, django_user_model, operator):
    member = django_user_model.objects.create_user(username="noted-user")
    client.force_login(operator)

    created = client.post(
        reverse("studio_member_note_create", args=(member.pk,)),
        {"body": "First note", "kind": "support", "visibility": "internal", "tags": "vip"},
    )
    note = MemberNote.objects.get()
    assert created.status_code == 302
    assert note.created_by == operator
    assert note.tags == ["vip"]

    edited = client.post(
        reverse("studio_member_note_edit", args=(member.pk, note.pk)),
        {"body": "Updated note", "kind": "outreach", "visibility": "external"},
    )
    note.refresh_from_db()
    assert edited.status_code == 302
    assert note.body == "Updated note"
    assert note.visibility == MemberNote.Visibility.EXTERNAL

    deleted = client.post(reverse("studio_member_note_delete", args=(member.pk, note.pk)))
    assert deleted.status_code == 302
    assert not MemberNote.objects.exists()


def test_note_create_normalizes_unknown_choices(client, django_user_model, operator):
    member = django_user_model.objects.create_user(username="choice-user")
    client.force_login(operator)

    client.post(
        reverse("studio_member_note_create", args=(member.pk,)),
        {"body": "Bounded choices", "kind": "unknown", "visibility": "public"},
    )

    note = MemberNote.objects.get()
    assert note.kind == MemberNote.Kind.GENERAL
    assert note.visibility == MemberNote.Visibility.INTERNAL


def test_user_pages_require_staff(client, django_user_model):
    member = django_user_model.objects.create_user(username="ordinary-user")
    client.force_login(member)

    assert client.get(reverse("studio_user_list")).status_code == 403
    assert client.get(reverse("studio_user_detail", args=(member.pk,))).status_code == 403


def test_note_visibility_manager_never_exposes_internal_notes_to_member(
    django_user_model, operator
):
    member = django_user_model.objects.create_user(username="member-reader")
    other = django_user_model.objects.create_user(username="other-reader")
    internal = MemberNote.objects.create(member=member, body="internal")
    external = MemberNote.objects.create(
        member=member, body="external", visibility=MemberNote.Visibility.EXTERNAL
    )
    MemberNote.objects.create(
        member=other, body="other external", visibility=MemberNote.Visibility.EXTERNAL
    )

    assert list(MemberNote.objects.visible_to(member)) == [external]
    assert set(MemberNote.objects.visible_to(operator)) == set(MemberNote.objects.all())
    assert internal not in MemberNote.objects.visible_to(member)
