import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory

from community_base.api.models import APIKey


@pytest.mark.django_db
def test_create_authenticate_and_revoke_key():
    user = get_user_model().objects.create_user(username="operator", is_staff=True)

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
    user = get_user_model().objects.create_user(username="member")

    with pytest.raises(ValidationError, match="Staff API keys require a staff user"):
        APIKey.create_for_user(
            user=user,
            name="Wrong kind",
            scopes=["fixtures.read"],
            kind=APIKey.Kind.STAFF,
        )


@pytest.mark.django_db
def test_mark_used_hashes_ip_address():
    user = get_user_model().objects.create_user(username="member")
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
