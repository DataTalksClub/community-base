from dataclasses import FrozenInstanceError, fields
from importlib import reload

import pytest
from django.core.cache import cache

from community_base.config import registry, service
from community_base.config.models import Setting
from community_base.config.registry import declare, definition, definitions, groups
from community_base.coursework import settings_keys
from community_base.coursework.automation import (
    COURSEWORK_AUTOMATION_KEY,
    GUARDED_HANDLERS,
    GUARDED_OPERATIONS,
    get_automation_policy,
)
from community_base.jobs.registry import registered_handler_names, registered_schedules

pytestmark = pytest.mark.django_db

EXPECTED_HANDLERS = (
    "coursework.form_pooled_batches",
    "coursework.expire_pooled_reviews",
    "coursework.send_homework_deadline_reminders",
    "coursework.send_project_submission_deadline_reminders",
    "coursework.send_peer_review_deadline_reminders",
)
EXPECTED_OPERATIONS = (
    "try_form_batch",
    "form_pooled_batches",
    "try_score_batch",
)


@pytest.fixture(autouse=True)
def reset_automation_config(monkeypatch):
    Setting.objects.filter(key=COURSEWORK_AUTOMATION_KEY).delete()
    monkeypatch.delenv(COURSEWORK_AUTOMATION_KEY, raising=False)
    monkeypatch.delenv("DJANGO_QCLUSTER_PROCESS", raising=False)
    cache.clear()
    service.runtime.reset()
    yield
    service.runtime.reset()
    cache.clear()


def test_package_definition_is_visible_and_operator_documented():
    declared = definition(COURSEWORK_AUTOMATION_KEY)

    assert declared.key == COURSEWORK_AUTOMATION_KEY
    assert declared.value_type == "bool"
    assert declared.default is True
    assert declared.secret is False
    assert declared.django_settings_fallback == COURSEWORK_AUTOMATION_KEY
    assert declared.env_var == COURSEWORK_AUTOMATION_KEY
    assert declared.docs_url == "community_base/coursework/README.md#automation-guard"
    assert declared in definitions()
    assert declared in groups()["coursework"]


def test_consumer_definition_loaded_first_remains_authoritative():
    package_definition = definition(COURSEWORK_AUTOMATION_KEY)
    registry._definitions.pop(COURSEWORK_AUTOMATION_KEY)
    try:
        consumer_definition = declare(
            key=COURSEWORK_AUTOMATION_KEY,
            group="consumer",
            label="Consumer coursework automation",
            description="Consumer-owned startup default.",
            value_type="bool",
            default=False,
            django_settings_fallback="CONSUMER_COURSEWORK_AUTOMATION",
            docs_url="consumer/docs.md#coursework-automation",
        )

        reload(settings_keys)

        assert definition(COURSEWORK_AUTOMATION_KEY) == consumer_definition
    finally:
        registry._definitions[COURSEWORK_AUTOMATION_KEY] = package_definition


def test_default_and_fallback_precedence_use_the_public_policy(monkeypatch, settings):
    assert get_automation_policy().enabled is True

    settings.COURSEWORK_AUTOMATION_ENABLED = False
    service.runtime.reset()
    assert get_automation_policy().enabled is False

    monkeypatch.setenv(COURSEWORK_AUTOMATION_KEY, "true")
    service.runtime.reset()
    assert get_automation_policy().enabled is True

    service.set(COURSEWORK_AUTOMATION_KEY, False, "test:policy")
    assert get_automation_policy().enabled is False

    service.unset(COURSEWORK_AUTOMATION_KEY, "test:policy")
    assert get_automation_policy().enabled is True


def test_web_policy_changes_after_supported_writes(
    monkeypatch, settings, django_capture_on_commit_callbacks
):
    settings.COURSEWORK_AUTOMATION_ENABLED = False
    monkeypatch.setenv(COURSEWORK_AUTOMATION_KEY, "true")
    assert get_automation_policy().enabled is True

    with django_capture_on_commit_callbacks(execute=True):
        service.set(COURSEWORK_AUTOMATION_KEY, False, "test:web")
    assert get_automation_policy().enabled is False

    with django_capture_on_commit_callbacks(execute=True):
        service.set(COURSEWORK_AUTOMATION_KEY, True, "test:web")
    assert get_automation_policy().enabled is True

    with django_capture_on_commit_callbacks(execute=True):
        service.unset(COURSEWORK_AUTOMATION_KEY, "test:web")
    assert get_automation_policy().enabled is True


def test_worker_policy_reads_each_supported_database_change(monkeypatch, settings):
    monkeypatch.setenv("DJANGO_QCLUSTER_PROCESS", "true")
    settings.COURSEWORK_AUTOMATION_ENABLED = False
    monkeypatch.setenv(COURSEWORK_AUTOMATION_KEY, "true")
    assert get_automation_policy().enabled is True

    service.set(COURSEWORK_AUTOMATION_KEY, False, "test:worker")
    assert get_automation_policy().enabled is False

    service.set(COURSEWORK_AUTOMATION_KEY, True, "test:worker")
    assert get_automation_policy().enabled is True

    service.unset(COURSEWORK_AUTOMATION_KEY, "test:worker")
    assert get_automation_policy().enabled is True


def test_policy_shape_is_immutable_minimal_and_ordered():
    policy = get_automation_policy()

    assert type(policy.enabled) is bool
    assert policy.guard_version == "1"
    assert policy.guarded_handlers == EXPECTED_HANDLERS == GUARDED_HANDLERS
    assert policy.guarded_operations == EXPECTED_OPERATIONS == GUARDED_OPERATIONS
    assert isinstance(policy.guarded_handlers, tuple)
    assert isinstance(policy.guarded_operations, tuple)
    assert {field.name for field in fields(policy)} == {
        "enabled",
        "guard_version",
        "guarded_handlers",
        "guarded_operations",
    }
    with pytest.raises(FrozenInstanceError):
        policy.enabled = False


def test_handlers_and_pooled_schedules_keep_the_exact_registry_contract():
    registered = set(registered_handler_names())
    schedules = {item.name: item for item in registered_schedules()}

    assert all(name in registered for name in EXPECTED_HANDLERS)
    assert schedules["coursework.form_pooled_batches.every_15_minutes"].handler == (
        "coursework.form_pooled_batches"
    )
    assert schedules["coursework.form_pooled_batches.every_15_minutes"].cron == "*/15 * * * *"
    assert schedules["coursework.expire_pooled_reviews.every_15_minutes"].handler == (
        "coursework.expire_pooled_reviews"
    )
    assert schedules["coursework.expire_pooled_reviews.every_15_minutes"].cron == "*/15 * * * *"

    service.set(COURSEWORK_AUTOMATION_KEY, False, "test:registry-contract")
    assert set(registered_handler_names()) == registered
    assert {item.name: item for item in registered_schedules()} == schedules
