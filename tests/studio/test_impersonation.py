import pytest
from django.contrib.auth import SESSION_KEY as AUTH_SESSION_KEY

from community_base.studio.impersonation import SESSION_KEY

pytestmark = pytest.mark.django_db


@pytest.fixture
def audit_events(settings):
    events = []
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "STUDIO_AUDIT_WRITER": lambda **event: events.append(event),
    }
    return events


@pytest.fixture
def users(django_user_model):
    actor = django_user_model.objects.create_user(
        username="studio-root", is_staff=True, is_superuser=True
    )
    target = django_user_model.objects.create_user(username="studio-target")
    return actor, target


def test_only_superusers_can_start_impersonation(client, django_user_model, users):
    _, target = users
    staff = django_user_model.objects.create_user(username="staff-only", is_staff=True)
    client.force_login(staff)

    response = client.post(f"/studio/impersonate/{target.pk}/")

    assert response.status_code == 403
    assert SESSION_KEY not in client.session


def test_start_and_stop_are_audited_and_restore_superuser(client, users, audit_events):
    actor, target = users
    client.force_login(actor)

    start = client.post(f"/studio/impersonate/{target.pk}/")

    assert start.status_code == 302
    assert int(client.session[AUTH_SESSION_KEY]) == target.pk
    assert client.session[SESSION_KEY] == actor.pk
    assert audit_events[0]["event"] == "studio.impersonation.started"
    assert audit_events[0]["actor_ref"] == str(actor.pk)
    assert "email" not in str(audit_events[0]).lower()

    stop = client.post("/studio/impersonate/stop/")

    assert stop.status_code == 302
    assert int(client.session[AUTH_SESSION_KEY]) == actor.pk
    assert SESSION_KEY not in client.session
    assert audit_events[1]["event"] == "studio.impersonation.stopped"


def test_superuser_target_is_refused(client, django_user_model, users, audit_events):
    actor, _ = users
    target = django_user_model.objects.create_user(
        username="another-root", is_staff=True, is_superuser=True
    )
    client.force_login(actor)

    response = client.post(f"/studio/impersonate/{target.pk}/")

    assert response.status_code == 302
    assert int(client.session[AUTH_SESSION_KEY]) == actor.pk
    assert audit_events[0]["event"] == "studio.impersonation.refused"


def test_stop_rejects_external_next_url(client, users, audit_events):
    actor, target = users
    client.force_login(actor)
    client.post(f"/studio/impersonate/{target.pk}/")

    response = client.post("/studio/impersonate/stop/", {"next": "https://attacker.invalid/steal"})

    assert response["Location"] == "/"


@pytest.mark.parametrize(
    "unsafe_next",
    ["//attacker.invalid/steal", "/foo\\bar", "/foo\nbar", "/studio/", "/admin/"],
)
def test_stop_rejects_malformed_and_sensitive_next_urls(client, users, audit_events, unsafe_next):
    actor, target = users
    client.force_login(actor)
    client.post(f"/studio/impersonate/{target.pk}/")

    response = client.post("/studio/impersonate/stop/", {"next": unsafe_next})

    assert response["Location"] == "/"
