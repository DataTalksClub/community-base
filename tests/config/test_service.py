import pytest
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured

from community_base.config import service
from community_base.config.models import Setting, SettingChange
from community_base.config.registry import declare
from community_base.kernel.redaction import REDACTED

STRING_KEY = "TEST_CONFIG_STRING"
SECRET_KEY = "TEST_CONFIG_SECRET"
FALLBACK_KEY = "TEST_CONFIG_FALLBACK"

declare(
    key=STRING_KEY,
    group="testing",
    label="String",
    description="String resolution test.",
    value_type="str",
    default="registry-default",
    env_var="TEST_CONFIG_STRING_ENV",
)
declare(
    key=SECRET_KEY,
    group="testing",
    label="Secret",
    description="Secret storage test.",
    value_type="str",
    default="",
    secret=True,
    optional=True,
)
declare(
    key=FALLBACK_KEY,
    group="testing",
    label="Fallback",
    description="Django fallback test.",
    value_type="str",
    default="registry-default",
    env_var="TEST_CONFIG_FALLBACK_ENV",
    django_settings_fallback="TEST_CONFIG_DJANGO_VALUE",
)


@pytest.fixture(autouse=True)
def reset_runtime(monkeypatch):
    cache.clear()
    service.runtime.reset()
    monkeypatch.delenv("TEST_CONFIG_STRING_ENV", raising=False)
    monkeypatch.delenv("TEST_CONFIG_FALLBACK_ENV", raising=False)
    yield
    service.runtime.reset()
    cache.clear()


@pytest.mark.django_db
def test_resolution_order_is_database_environment_django_then_default(monkeypatch, settings):
    settings.TEST_CONFIG_DJANGO_VALUE = "django"
    monkeypatch.setenv("TEST_CONFIG_FALLBACK_ENV", "environment")

    assert service.get(FALLBACK_KEY) == "environment"
    service.set(FALLBACK_KEY, "database", "test:actor")
    assert service.get(FALLBACK_KEY) == "database"

    Setting.objects.filter(key=FALLBACK_KEY).delete()
    service.runtime.publish()
    assert service.get(FALLBACK_KEY) == "environment"
    monkeypatch.delenv("TEST_CONFIG_FALLBACK_ENV")
    service.runtime.reset()
    assert service.get(FALLBACK_KEY) == "django"
    del settings.TEST_CONFIG_DJANGO_VALUE
    service.runtime.reset()
    assert service.get(FALLBACK_KEY) == "registry-default"
    assert service.get(FALLBACK_KEY, "call-default") == "call-default"


@pytest.mark.django_db
def test_secrets_are_encrypted_and_redacted_from_export_and_audit():
    service.set(
        SECRET_KEY,
        "test-secret-value",
        "test:actor",
        "Replace test-secret-value",
    )

    row = Setting.objects.get(key=SECRET_KEY)
    change = SettingChange.objects.get(setting_key=SECRET_KEY)
    assert row.value.startswith("fernet:v1:")
    assert "test-secret-value" not in row.value
    assert service.get(SECRET_KEY) == "test-secret-value"
    assert service.export()[SECRET_KEY] == REDACTED
    assert change.new_value == REDACTED
    assert change.new_value_redacted
    assert "test-secret-value" not in change.reason


@pytest.mark.django_db(transaction=True)
def test_shared_stamp_invalidates_another_runtime_instance():
    first = service.RuntimeConfig(stamp_store=cache)
    second = service.RuntimeConfig(stamp_store=cache)
    assert first.value(STRING_KEY) == "registry-default"
    assert second.value(STRING_KEY) == "registry-default"

    service.set(STRING_KEY, "new-value", "test:actor")

    assert first.value(STRING_KEY) == "new-value"
    assert second.value(STRING_KEY) == "new-value"


@pytest.mark.django_db
def test_worker_reads_database_without_local_cache(monkeypatch):
    service.set(STRING_KEY, "first", "test:actor")
    assert service.get(STRING_KEY) == "first"
    Setting.objects.filter(key=STRING_KEY).update(value="second")
    monkeypatch.setattr(service, "running_in_worker_process", lambda: True)

    assert service.get(STRING_KEY) == "second"


@pytest.mark.django_db
def test_import_is_atomic_when_a_key_is_unknown():
    with pytest.raises(ImproperlyConfigured, match="Unknown configuration key"):
        service.import_(
            {STRING_KEY: "would-be-written", "UNKNOWN_IMPORT_KEY": "bad"},
            "test:actor",
        )

    assert not Setting.objects.filter(key=STRING_KEY).exists()
