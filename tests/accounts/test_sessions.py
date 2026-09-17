from importlib import import_module

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore as DefaultSessionStore
from django.test import override_settings
from django.utils import timezone

from community_base.accounts.models import AccountSession
from community_base.accounts.services.sessions import (
    erase_member_sessions,
    purge_expired_sessions,
)
from community_base.accounts.session_backend import SessionStore as AccountSessionStore

pytestmark = pytest.mark.django_db


def _current_session_store_class():
    """Resolve `SessionStore` the same way Django's own session middleware does."""
    engine = import_module(settings.SESSION_ENGINE)
    return engine.SessionStore


def test_session_engine_defaults_to_djangos_own_backend():
    # `community_base.accounts` is installed in the test project and SESSION_ENGINE is not
    # set anywhere, so Django's documented default applies untouched.
    assert getattr(settings, "SESSION_ENGINE", "django.contrib.sessions.backends.db") == (
        "django.contrib.sessions.backends.db"
    )
    assert _current_session_store_class() is DefaultSessionStore


def test_opting_out_leaves_default_session_behaviour_untouched():
    user = get_user_model().objects.create_user("opted-out@example.com")
    store_class = _current_session_store_class()
    assert store_class is DefaultSessionStore

    store = store_class()
    store["_auth_user_id"] = str(user.pk)
    store.save()
    session_key = store.session_key

    # Django's stock backend round-trips the session normally, unaware this app exists.
    reloaded = store_class(session_key)
    assert reloaded["_auth_user_id"] == str(user.pk)

    # The row is visible through the queryable model (it is the same `django_session`
    # table), but the column Django's own backend never writes stays null.
    row = AccountSession.objects.get(session_key=session_key)
    assert row.account_id is None


@override_settings(SESSION_ENGINE="community_base.accounts.session_backend")
def test_opting_in_records_account_id_on_the_queryable_session():
    user = get_user_model().objects.create_user("opted-in@example.com")
    store_class = _current_session_store_class()
    assert store_class is AccountSessionStore

    store = store_class()
    store["_auth_user_id"] = str(user.pk)
    store.save()
    session_key = store.session_key

    reloaded = store_class(session_key)
    assert reloaded["_auth_user_id"] == str(user.pk)

    row = AccountSession.objects.get(session_key=session_key)
    assert row.account_id == user.pk


@override_settings(SESSION_ENGINE="community_base.accounts.session_backend")
def test_erase_member_sessions_deletes_only_that_members_rows():
    member = get_user_model().objects.create_user("member@example.com")
    other = get_user_model().objects.create_user("other@example.com")
    for user in (member, other):
        store = AccountSessionStore()
        store["_auth_user_id"] = str(user.pk)
        store.save()

    deleted = erase_member_sessions(member)

    assert deleted == 1
    assert not AccountSession.objects.filter(account_id=member.pk).exists()
    assert AccountSession.objects.filter(account_id=other.pk).exists()


def test_erase_member_sessions_is_a_service_not_a_row_scan():
    # Erasure matches only rows already carrying `account_id`; it never decodes
    # `session_data` to find a member's sessions.
    user = get_user_model().objects.create_user("scanless@example.com")
    store = DefaultSessionStore()
    store["_auth_user_id"] = str(user.pk)
    store.save()

    deleted = erase_member_sessions(user)

    assert deleted == 0
    assert AccountSession.objects.filter(session_key=store.session_key).exists()


@override_settings(SESSION_ENGINE="community_base.accounts.session_backend")
def test_purge_expired_sessions_deletes_only_expired_rows():
    user = get_user_model().objects.create_user("expiring@example.com")
    expired_store = AccountSessionStore()
    expired_store["_auth_user_id"] = str(user.pk)
    expired_store.set_expiry(-1)
    expired_store.save()

    live_store = AccountSessionStore()
    live_store["_auth_user_id"] = str(user.pk)
    live_store.save()

    deleted = purge_expired_sessions(now=timezone.now())

    assert deleted == 1
    assert not AccountSession.objects.filter(session_key=expired_store.session_key).exists()
    assert AccountSession.objects.filter(session_key=live_store.session_key).exists()


@override_settings(SESSION_ENGINE="community_base.accounts.session_backend")
def test_purge_expired_sessions_honours_a_batch_limit():
    user = get_user_model().objects.create_user("batched@example.com")
    for _ in range(3):
        store = AccountSessionStore()
        store["_auth_user_id"] = str(user.pk)
        store.set_expiry(-1)
        store.save()

    deleted = purge_expired_sessions(now=timezone.now(), limit=2)

    assert deleted == 2
    assert AccountSession.objects.filter(account_id=user.pk).count() == 1
