import pytest

from community_base.studio.user_tags import get_tags, normalize_tags, set_tags


def test_tag_normalization_is_stable_and_unique():
    assert normalize_tags([" Early Adopter ", "early_adopter", "Speaker!"]) == [
        "early-adopter",
        "speaker",
    ]


@pytest.mark.django_db
def test_default_accessor_reads_and_writes_shared_user_tags(settings, django_user_model):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "USER_TAGS_ACCESSOR": "community_base.studio.user_tags.AttributeTagsAccessor",
    }
    user = django_user_model.objects.create_user(email="no-tags-field@example.com")

    assert get_tags(user) == []
    set_tags(user, ["Early Adopter"])
    user.refresh_from_db()
    assert user.tags == ["early-adopter"]
