import pytest
from django.core.exceptions import ImproperlyConfigured

from community_base.studio.user_tags import get_tags, normalize_tags, set_tags


def test_tag_normalization_is_stable_and_unique():
    assert normalize_tags([" Early Adopter ", "early_adopter", "Speaker!"]) == [
        "early-adopter",
        "speaker",
    ]


@pytest.mark.django_db
def test_default_accessor_is_read_only_when_user_has_no_tags(settings, django_user_model):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "USER_TAGS_ACCESSOR": "community_base.studio.user_tags.AttributeTagsAccessor",
    }
    user = django_user_model.objects.create_user(username="no-tags-field")

    assert get_tags(user) == []
    with pytest.raises(ImproperlyConfigured, match="USER_TAGS_ACCESSOR"):
        set_tags(user, ["tag"])
