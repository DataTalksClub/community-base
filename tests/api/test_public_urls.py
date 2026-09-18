from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django.urls import NoReverseMatch

from community_base.api.public_urls import public_url


class Resource:
    def __init__(self, route):
        self.route = route

    def get_absolute_url(self):
        return self.route


def configured(settings, **values):
    result = dict(settings.COMMUNITY_BASE)
    result.update(values)
    return result


def test_public_url_normalizes_site_origin_and_path(settings):
    resource = Resource("/events/example/")

    for site_url in ("https://example.org", "https://example.org/"):
        with override_settings(COMMUNITY_BASE=configured(settings, SITE_URL=site_url)):
            assert public_url(resource, is_public=True) == "https://example.org/events/example/"


def test_public_url_preserves_a_configured_site_path(settings):
    resource = Resource("/courses/mlops")

    with override_settings(
        COMMUNITY_BASE=configured(settings, SITE_URL="https://example.org/community/")
    ):
        assert public_url(resource, is_public=True) == "https://example.org/community/courses/mlops"


def test_public_url_does_not_fabricate_unpublished_or_unreachable_resources(settings):
    resource = Resource("/events/draft/")
    unavailable = Resource(None)

    with override_settings(COMMUNITY_BASE=configured(settings, SITE_URL="https://example.org")):
        assert public_url(resource, is_public=False) is None
        assert public_url(object(), is_public=True) is None

        unavailable.get_absolute_url = lambda: (_ for _ in ()).throw(NoReverseMatch())
        assert public_url(unavailable, is_public=True) is None

        unavailable.get_absolute_url = lambda: (_ for _ in ()).throw(ImproperlyConfigured())
        assert public_url(unavailable, is_public=True) is None
