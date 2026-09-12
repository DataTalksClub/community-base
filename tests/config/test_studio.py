import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from community_base.config import service
from community_base.config.models import SettingChange
from community_base.config.registry import declare

STUDIO_TEXT_KEY = "TEST_STUDIO_TEXT"
STUDIO_SECRET_KEY = "TEST_STUDIO_SECRET"

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


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user(username="config-staff", is_staff=True)


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
    user = get_user_model().objects.create_user(username="config-member")
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


OPTIONAL_INT_KEY = "TEST_STUDIO_OPTIONAL_INT"
RESTART_KEY = "TEST_STUDIO_RESTART"
declare(
    key=OPTIONAL_INT_KEY,
    group="optional_integer_testing",
    label="Optional integer",
    description="Blank removes the override.",
    value_type="int",
    default=3,
    optional=True,
    env_var="TEST_STUDIO_OPTIONAL_INT_ENV",
)
declare(
    key=RESTART_KEY,
    group="restart_testing",
    label="Startup value",
    description="Applied at startup.",
    value_type="str",
    default="initial",
    requires_restart=True,
)


@pytest.mark.django_db(transaction=True)
def test_blank_optional_integer_clears_existing_override_and_uses_environment(
    client, staff_user, monkeypatch
):
    from community_base.config.models import Setting

    monkeypatch.setenv("TEST_STUDIO_OPTIONAL_INT_ENV", "7")
    service.set(OPTIONAL_INT_KEY, 12, "test:actor")
    client.force_login(staff_user)

    response = client.post(
        reverse("community_base_settings_save_group", args=("optional_integer_testing",)),
        {OPTIONAL_INT_KEY: ""},
        follow=True,
    )

    assert response.status_code == 200
    assert not Setting.objects.filter(key=OPTIONAL_INT_KEY).exists()
    assert service.get(OPTIONAL_INT_KEY) == 7
    assert service.resolved_source(OPTIONAL_INT_KEY) == "environment"
    change = SettingChange.objects.filter(setting_key=OPTIONAL_INT_KEY).latest("created_at")
    assert change.old_value == 12
    assert change.new_value is None
    assert change.actor_ref == f"user:{staff_user.pk}"
    assert b"Cleared 1 override(s)" in response.content


@pytest.mark.django_db(transaction=True)
def test_blank_secret_preserves_existing_override(client, staff_user):
    service.set(STUDIO_SECRET_KEY, "kept-secret", "test:actor")
    client.force_login(staff_user)

    response = client.post(
        reverse("community_base_settings_save_group", args=("studio_testing",)),
        {STUDIO_TEXT_KEY: "changed", STUDIO_SECRET_KEY: ""},
    )

    assert response.status_code == 302
    assert service.get(STUDIO_SECRET_KEY) == "kept-secret"
    assert SettingChange.objects.filter(setting_key=STUDIO_SECRET_KEY).count() == 1


@pytest.mark.django_db(transaction=True)
def test_restart_metadata_and_feedback_only_for_changed_value(client, staff_user):
    client.force_login(staff_user)
    url = reverse("community_base_settings_save_group", args=("restart_testing",))

    changed = client.post(url, {RESTART_KEY: "changed"}, follow=True)
    unchanged = client.post(url, {RESTART_KEY: "changed"}, follow=True)

    assert changed.status_code == 200
    assert b"Restart the application" in changed.content
    assert b"Requires restart" in changed.content
    assert service.describe(RESTART_KEY)["requires_restart"] is True
    assert unchanged.status_code == 200
    assert b"Restart the application" not in unchanged.content


@pytest.mark.django_db(transaction=True)
def test_invalid_optional_integer_does_not_modify_override(client, staff_user):
    service.set(OPTIONAL_INT_KEY, 12, "test:actor")
    client.force_login(staff_user)

    response = client.post(
        reverse("community_base_settings_save_group", args=("optional_integer_testing",)),
        {OPTIONAL_INT_KEY: "invalid"},
        follow=True,
    )

    assert response.status_code == 200
    assert b"Could not save" in response.content
    assert service.get(OPTIONAL_INT_KEY) == 12


@pytest.mark.parametrize(("optional", "raw", "valid"), [(False, "", False), (True, "0", True)])
def test_integer_form_required_blank_and_zero_contract(optional, raw, valid):
    from community_base.config.forms import SettingsGroupForm
    from community_base.config.registry import Definition

    item = Definition(
        key="TEST_FORM_INT",
        group="form",
        label="Integer",
        description="Integer.",
        value_type="int",
        default=3,
        optional=optional,
    )
    form = SettingsGroupForm(
        {item.key: raw},
        definitions=(item,),
        initial_values={item.key: 12},
    )

    assert form.is_valid() is valid
    if valid:
        assert form.cleaned_updates() == {item.key: 0}
        assert form.cleaned_clears() == ()
