import pytest
from django.contrib.auth import BACKEND_SESSION_KEY
from django.contrib.auth import SESSION_KEY as AUTH_SESSION_KEY

from community_base.studio.impersonation import SESSION_KEY

pytestmark = pytest.mark.django_db

CUSTOM_BACKEND = "tests.studio.custom_auth_backend.DurableAccountBackend"
ALTERNATE_MOUNT_URLCONF = "tests.studio.site_with_studio_at_another_path"
ALTERNATE_NAMESPACED_MOUNT_URLCONF = "tests.studio.site_with_namespaced_studio_at_another_path"


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
        email="studio-root@example.com", is_staff=True, is_superuser=True
    )
    target = django_user_model.objects.create_user(email="studio-target@example.com")
    return actor, target


def test_only_superusers_can_start_impersonation(client, django_user_model, users):
    _, target = users
    staff = django_user_model.objects.create_user(email="staff-only@example.com", is_staff=True)
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
        email="another-root@example.com", is_staff=True, is_superuser=True
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


def test_default_site_still_uses_model_backend(client, users, audit_events):
    """A site that never configures `AUTHENTICATION_BACKENDS` gets Django's own
    default, `["django.contrib.auth.backends.ModelBackend"]`, which is also the
    first entry in the package's own test settings. Pinned so picking the first
    configured backend does not change this, the one shape every current site
    already exercises.
    """

    actor, target = users
    client.force_login(actor)

    client.post(f"/studio/impersonate/{target.pk}/")

    assert client.session[BACKEND_SESSION_KEY] == "django.contrib.auth.backends.ModelBackend"


def test_impersonation_works_on_a_site_with_only_its_own_authentication_backend(
    client, users, audit_events, settings
):
    """The DataTalks.Club shape: `AUTHENTICATION_BACKENDS` names one backend, and
    it is not `ModelBackend`. The former hardcoded backend would return 302 and
    still break the very next request; this asserts the operator resolves
    correctly on the request right after `start`, and is restored correctly by
    `stop`, not merely that the redirect happened.
    """

    settings.AUTHENTICATION_BACKENDS = [CUSTOM_BACKEND]
    actor, target = users
    client.force_login(actor, backend=CUSTOM_BACKEND)

    start = client.post(f"/studio/impersonate/{target.pk}/")

    assert start.status_code == 302
    assert client.session[BACKEND_SESSION_KEY] == CUSTOM_BACKEND
    assert int(client.session[AUTH_SESSION_KEY]) == target.pk

    after_start = client.get("/studio/")
    assert after_start.wsgi_request.user.is_authenticated
    assert after_start.wsgi_request.user.pk == target.pk

    stop = client.post("/studio/impersonate/stop/")

    assert stop.status_code == 302
    assert client.session[BACKEND_SESSION_KEY] == CUSTOM_BACKEND
    assert int(client.session[AUTH_SESSION_KEY]) == actor.pk

    after_stop = client.get("/studio/")
    assert after_stop.wsgi_request.user.is_authenticated
    assert after_stop.wsgi_request.user.pk == actor.pk


@pytest.mark.parametrize(
    "urlconf",
    [ALTERNATE_MOUNT_URLCONF, ALTERNATE_NAMESPACED_MOUNT_URLCONF],
)
def test_return_guard_refuses_sensitive_pages_wherever_studio_is_mounted(
    client, users, audit_events, settings, urlconf
):
    """`/studio` used to be a literal, so a site mounting Studio at `manage/`
    (namespaced or not, both `tests/studio/site_with_*_at_another_path.py`
    fixtures from C7.19/C7.22) kept a guard shaped like it worked while it
    matched nothing: `/manage/users/` passed straight through.
    """

    settings.ROOT_URLCONF = urlconf
    actor, target = users
    client.force_login(actor)
    client.post(f"/manage/impersonate/{target.pk}/")

    response = client.post("/manage/impersonate/stop/", {"next": "/manage/users/"})

    assert response["Location"] == "/"


def test_return_guard_still_allows_a_page_outside_the_alternate_mount(
    client, users, audit_events, settings
):
    """The guard degrading to matching nothing would pass silently; so would it
    degrading to matching everything. This pins the other side: a page outside
    the Studio mount and outside the fixed prefixes is still a legal target.
    """

    settings.ROOT_URLCONF = ALTERNATE_MOUNT_URLCONF
    actor, target = users
    client.force_login(actor)
    client.post(f"/manage/impersonate/{target.pk}/")

    response = client.post("/manage/impersonate/stop/", {"next": "/blog/post-1/"})

    assert response["Location"] == "/blog/post-1/"
