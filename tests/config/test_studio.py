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
