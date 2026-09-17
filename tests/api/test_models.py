import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory

from community_base.api.models import APIKey


@pytest.mark.django_db
def test_create_authenticate_and_revoke_key():
    user = get_user_model().objects.create_user(email="operator@example.com", is_staff=True)

    api_key, plaintext = APIKey.create_for_user(
        user=user,
        name=" Import client ",
        scopes=["settings.write", "fixtures.read", "fixtures.read"],
        kind=APIKey.Kind.STAFF,
    )

    assert plaintext.startswith("cb_staff_")
    assert plaintext not in api_key.key_hash
    assert api_key.name == "Import client"
    assert api_key.scopes == ["fixtures.read", "settings.write"]
    assert APIKey.authenticate(plaintext) == api_key
    api_key.revoke()
    assert APIKey.authenticate(plaintext) is None


@pytest.mark.django_db
def test_staff_key_rejects_non_staff_owner():
    user = get_user_model().objects.create_user(email="member@example.com")

    with pytest.raises(ValidationError, match="Staff API keys require a staff user"):
        APIKey.create_for_user(
            user=user,
            name="Wrong kind",
            scopes=["fixtures.read"],
            kind=APIKey.Kind.STAFF,
        )


@pytest.mark.django_db
def test_staff_key_stops_authenticating_when_owner_is_downgraded():
    user = get_user_model().objects.create_user(email="operator@example.com", is_staff=True)
    _, plaintext = APIKey.create_for_user(
        user=user,
        name="Staff client",
        scopes=["fixtures.read"],
        kind=APIKey.Kind.STAFF,
    )

    user.is_staff = False
    user.save(update_fields=("is_staff",))

    assert APIKey.authenticate(plaintext) is None


@pytest.mark.django_db
def test_a_downgraded_owners_key_can_still_be_revoked():
    """Losing staff status must not make a key unrevokable.

    ``save()`` runs ``full_clean()``, and ``clean()`` refuses a staff key whose
    owner is not staff, so any lifecycle operation written as ``key.save()``
    raises on a row whose owner has since been downgraded. That is precisely the
    moment an operator most wants to revoke the key.

    The package sidesteps it by writing every post-creation change through a
    queryset ``update()``: ``revoke()`` and ``mark_used()`` both do, and the only
    ``save()`` is at creation. This test pins that, because the constraint is
    invisible from the call site and a site or a future change that reaches for
    ``save()`` here would raise instead of revoking.
    """

    user = get_user_model().objects.create_user(email="downgraded@example.com", is_staff=True)
    key, plaintext = APIKey.create_for_user(
        user=user,
        name="Staff client",
        scopes=["fixtures.read"],
        kind=APIKey.Kind.STAFF,
    )
    user.is_staff = False
    user.save(update_fields=("is_staff",))

    key.revoke()

    key.refresh_from_db()
    assert key.revoked_at is not None
    assert APIKey.authenticate(plaintext) is None


@pytest.mark.django_db
def test_saving_a_downgraded_owners_key_raises_which_is_why_revoke_uses_update():
    """The negative half of the rule above, stated so it cannot regress silently."""

    user = get_user_model().objects.create_user(email="downgraded-save@example.com", is_staff=True)
    key, _ = APIKey.create_for_user(
        user=user,
        name="Staff client",
        scopes=["fixtures.read"],
        kind=APIKey.Kind.STAFF,
    )
    user.is_staff = False
    user.save(update_fields=("is_staff",))
    key.refresh_from_db()

    with pytest.raises(ValidationError, match="Staff API keys require a staff user"):
        key.save()


@pytest.mark.django_db
def test_mark_used_hashes_ip_address():
    user = get_user_model().objects.create_user(email="member@example.com")
    api_key, _ = APIKey.create_for_user(
        user=user,
        name="Member client",
        scopes=["profile.read"],
        kind=APIKey.Kind.MEMBER,
    )
    request = RequestFactory().get("/", REMOTE_ADDR="192.0.2.1")

    api_key.mark_used(request)

    api_key.refresh_from_db()
    assert api_key.last_used_at is not None
    assert api_key.last_used_ip_hash
    assert "192.0.2.1" not in api_key.last_used_ip_hash
