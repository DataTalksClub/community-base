from django.apps import AppConfig as DjangoAppConfig
from django.apps import apps
from django.apps.registry import Apps

import community_base.curriculum.apps as curriculum_apps
from community_base.curriculum.apps import events_dependent_surfaces_active


def test_events_dependent_surfaces_active_when_events_is_installed():
    assert events_dependent_surfaces_active()


def test_events_dependent_surfaces_active_false_when_events_is_not_installed(monkeypatch):
    monkeypatch.setattr(apps, "is_installed", lambda name: False)
    assert not events_dependent_surfaces_active()


class _FakeEventsAppConfig(DjangoAppConfig):
    """A stand-in for `community_base.events.apps.EventsConfig` that carries the
    same `name`, used only to prove `apps.is_installed()` recognises the
    AppConfig-path spelling in `INSTALLED_APPS`.

    The real `EventsConfig.ready()` registers a Studio section and a mail
    context resolver into process-wide dictionaries that reject a second,
    duplicate registration, so it cannot safely run twice in one test
    process. This fake carries no `ready()` override (a no-op), so
    populating a second, fully isolated `Apps` registry with it is safe and
    touches nothing the rest of the suite depends on.
    """

    name = "community_base.events"
    label = "fake_events_for_appconfig_spelling_test"


def test_events_dependent_surfaces_active_true_for_the_appconfig_path_spelling(monkeypatch):
    """Regression test for the raw `INSTALLED_APPS` membership test this replaced.

    Django accepts either the plain module path or a dotted AppConfig class path for
    the same app; `"community_base.events" in set(INSTALLED_APPS)` only recognised
    the first, so a site spelling it the AppConfig way (a legal spelling Django
    accepts everywhere) silently never registered the curriculum Studio section or
    its API views. `apps.is_installed()` resolves both spellings to the same
    `AppConfig.name`, so this passes with the fix; the old membership test, given the
    same `INSTALLED_APPS` entry, would have said `False`.
    """

    entry = f"{__name__}._FakeEventsAppConfig"
    assert "community_base.events" not in {entry}  # the old raw check would miss it

    isolated = Apps(installed_apps=[entry])
    assert isolated.is_installed("community_base.events")

    monkeypatch.setattr(curriculum_apps, "apps", isolated)

    assert events_dependent_surfaces_active()
