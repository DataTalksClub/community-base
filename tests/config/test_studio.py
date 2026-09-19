import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from community_base.config import service
from community_base.config.models import Setting, SettingChange
from community_base.config.registry import declare

STUDIO_TEXT_KEY = "TEST_STUDIO_TEXT"
STUDIO_SECRET_KEY = "TEST_STUDIO_SECRET"
STUDIO_RESTART_KEY = "TEST_STUDIO_RESTART"
STUDIO_NO_RESTART_KEY = "TEST_STUDIO_NO_RESTART"

declare(
    key=STUDIO_TEXT_KEY,
    group="studio_testing",
    label="Studio text",
    description="Text edited in Studio.",
    value_type="str",
    default="initial",
)
declare(
    key=STUDIO_SECRET_KEY,
    group="studio_testing",
    label="Studio secret",
    description="Secret edited in Studio.",
    value_type="str",
    default="",
    secret=True,
    optional=True,
)
declare(
    key=STUDIO_RESTART_KEY,
    group="studio_restart_testing",
    label="Studio restart",
    description="Changing this needs a restart.",
    value_type="str",
    default="initial",
    requires_restart=True,
)
declare(
    key=STUDIO_NO_RESTART_KEY,
    group="studio_restart_testing",
    label="Studio no restart",
    description="Changing this does not need a restart.",
    value_type="str",
    default="initial",
)


def _section_html(html: str, group: str) -> str:
    start = html.index(f'id="group-{group}"')
    end = html.index("</section>", start)
    return html[start:end]


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user(email="config-staff@example.com", is_staff=True)


@pytest.mark.django_db(transaction=True)
def test_settings_page_renders_groups_and_never_renders_secret(client, staff_user):
    service.set(STUDIO_SECRET_KEY, "never-render-this", "test:actor")
    client.force_login(staff_user)

    response = client.get(reverse("community_base_settings"))

    assert response.status_code == 200
    assert b"studio_testing" in response.content
    assert b"never-render-this" not in response.content
    assert b"db" in response.content
    assert "no-cache" in response.headers["Cache-Control"]


def test_settings_page_rejects_non_staff(client, db):
    user = get_user_model().objects.create_user(email="config-member@example.com")
    client.force_login(user)

    response = client.get(reverse("community_base_settings"))

    assert response.status_code == 403


@pytest.mark.django_db(transaction=True)
def test_save_group_updates_values_and_writes_actor_audit(client, staff_user):
    client.force_login(staff_user)

    response = client.post(
        reverse("community_base_settings_save_group", args=("studio_testing",)),
        {STUDIO_TEXT_KEY: "changed", STUDIO_SECRET_KEY: "new-secret"},
    )

    assert response.status_code == 302
    assert service.get(STUDIO_TEXT_KEY) == "changed"
    assert service.get(STUDIO_SECRET_KEY) == "new-secret"
    change = SettingChange.objects.filter(setting_key=STUDIO_TEXT_KEY).latest("created_at")
    assert change.actor_ref == f"user:{staff_user.pk}"


@pytest.mark.django_db(transaction=True)
def test_studio_export_masks_secret_and_import_restores_non_secret(client, staff_user):
    service.set(STUDIO_SECRET_KEY, "export-secret", "test:actor")
    client.force_login(staff_user)

    exported = client.get(reverse("community_base_settings_export"))
    assert exported.status_code == 200
    assert exported.json()["settings"][STUDIO_SECRET_KEY] == "[REDACTED]"
    assert b"export-secret" not in exported.content

    imported = client.post(
        reverse("community_base_settings_import"),
        {
            "payload": json.dumps(
                {
                    "settings": {
                        STUDIO_TEXT_KEY: "imported",
                        STUDIO_SECRET_KEY: "[REDACTED]",
                    }
                }
            ),
            "reason": "Restore fixture",
        },
    )
    assert imported.status_code == 302
    assert service.get(STUDIO_TEXT_KEY) == "imported"
    assert service.get(STUDIO_SECRET_KEY) == "export-secret"


@pytest.mark.django_db(transaction=True)
def test_restart_badge_shown_only_for_settings_that_declare_it(client, staff_user):
    client.force_login(staff_user)

    response = client.get(reverse("community_base_settings"))

    section = _section_html(response.content.decode(), "studio_restart_testing")
    # TEST_STUDIO_NO_RESTART sorts before TEST_STUDIO_RESTART (registry.definitions()
    # orders by (group, key)), so splitting on the restart field's own input isolates
    # the no-restart field's markup from the restart field's markup.
    split_at = section.index(f'id="id_{STUDIO_RESTART_KEY}"')
    no_restart_markup, restart_markup = section[:split_at], section[split_at:]

    assert "Requires restart" not in no_restart_markup
    assert "Requires restart" in restart_markup


@pytest.mark.django_db(transaction=True)
def test_clear_control_is_offered_only_when_an_override_exists(client, staff_user):
    client.force_login(staff_user)

    before = client.get(reverse("community_base_settings"))
    assert f"{STUDIO_TEXT_KEY}__clear".encode() not in before.content

    service.set(STUDIO_TEXT_KEY, "overridden", "test:actor")
    after = client.get(reverse("community_base_settings"))
    assert f'name="{STUDIO_TEXT_KEY}__clear"'.encode() in after.content


@pytest.mark.django_db(transaction=True)
def test_clearing_an_override_falls_back_and_is_audited(client, staff_user):
    service.set(STUDIO_TEXT_KEY, "overridden", "test:actor", "Initial override")
    client.force_login(staff_user)

    response = client.post(
        reverse("community_base_settings_save_group", args=("studio_testing",)),
        {
            STUDIO_TEXT_KEY: "overridden",
            f"{STUDIO_TEXT_KEY}__clear": "on",
            STUDIO_SECRET_KEY: "",
        },
    )

    assert response.status_code == 302
    assert not Setting.objects.filter(key=STUDIO_TEXT_KEY).exists()
    assert service.get(STUDIO_TEXT_KEY) == "initial"
    change = SettingChange.objects.filter(setting_key=STUDIO_TEXT_KEY).latest("created_at")
    assert change.actor_ref == f"user:{staff_user.pk}"
    assert change.new_value is None
    assert change.old_value == "overridden"


@pytest.mark.django_db(transaction=True)
def test_clearing_a_required_setting_works_even_if_its_value_field_is_left_blank(
    client, staff_user
):
    """A required field's own validation must not block clearing its override:
    the operator's intent is to discard the value, not to supply a new one."""
    service.set(STUDIO_TEXT_KEY, "overridden", "test:actor")
    client.force_login(staff_user)

    response = client.post(
        reverse("community_base_settings_save_group", args=("studio_testing",)),
        {STUDIO_TEXT_KEY: "", f"{STUDIO_TEXT_KEY}__clear": "on", STUDIO_SECRET_KEY: ""},
    )

    assert response.status_code == 302
    assert not Setting.objects.filter(key=STUDIO_TEXT_KEY).exists()
    assert service.get(STUDIO_TEXT_KEY) == "initial"


@pytest.mark.django_db(transaction=True)
def test_saving_a_changed_restart_setting_warns_at_the_moment_of_the_change(client, staff_user):
    client.force_login(staff_user)

    response = client.post(
        reverse("community_base_settings_save_group", args=("studio_restart_testing",)),
        {STUDIO_RESTART_KEY: "changed", STUDIO_NO_RESTART_KEY: "initial"},
        follow=True,
    )

    assert response.status_code == 200
    assert b"Restart the application" in response.content
    assert STUDIO_RESTART_KEY.encode() in response.content


@pytest.mark.django_db(transaction=True)
def test_saving_an_unchanged_group_does_not_warn_about_restart(client, staff_user):
    client.force_login(staff_user)
    # The first save changes STUDIO_RESTART_KEY away from its default, so it does
    # warn; follow=True renders and so consumes that message before the second
    # POST, isolating what the second (unchanged) save reports on its own.
    client.post(
        reverse("community_base_settings_save_group", args=("studio_restart_testing",)),
        {STUDIO_RESTART_KEY: "same-value", STUDIO_NO_RESTART_KEY: "initial"},
        follow=True,
    )

    response = client.post(
        reverse("community_base_settings_save_group", args=("studio_restart_testing",)),
        {STUDIO_RESTART_KEY: "same-value", STUDIO_NO_RESTART_KEY: "initial"},
        follow=True,
    )

    assert response.status_code == 200
    assert b"Restart the application" not in response.content


@pytest.mark.django_db(transaction=True)
def test_saving_a_changed_non_restart_setting_does_not_warn(client, staff_user):
    client.force_login(staff_user)

    response = client.post(
        reverse("community_base_settings_save_group", args=("studio_testing",)),
        {STUDIO_TEXT_KEY: "changed", STUDIO_SECRET_KEY: ""},
        follow=True,
    )

    assert response.status_code == 200
    assert b"Restart the application" not in response.content
