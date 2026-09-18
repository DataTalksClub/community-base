"""Site shapes the package handles correctly today, pinned so a change cannot drop them.

Everything here passes on this commit. The audit
(`docs/plan/evidence/adoption-assumption-audit-2026-09-18.md`) records the shapes that do
NOT pass; those are separate issues and are deliberately not asserted here, because a
failing test in the tree is indistinguishable from a broken build to the next reader.

The point of the file is the other half of the audit: a behaviour that only happens to be
right is one edit away from being wrong, and nothing was watching it.
"""

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory, override_settings

from community_base.kernel import conf
from community_base.studio import registry, route_checks, user_tags, user_views
from community_base.studio.templatetags import studio_filters

ALTERNATE_MOUNT_URLCONF = "tests.studio.site_with_studio_at_another_path"


def test_unknown_setting_is_refused_rather_than_defaulted():
    """A key the package does not declare is a typo; the site hears about it."""

    with pytest.raises(ImproperlyConfigured):
        conf.get("STUDIO_TITEL")


def test_declared_setting_falls_back_when_the_site_omits_it():
    with override_settings(COMMUNITY_BASE={}):
        assert conf.get("STUDIO_TITLE") == conf.DEFAULTS["STUDIO_TITLE"]


def test_destination_url_degrades_instead_of_raising():
    """An unmounted route name renders an empty href, never a 500 on the whole shell."""

    destination = registry.Destination(
        key="nowhere",
        title="Nowhere",
        url_name="studio_route_this_site_does_not_mount",
        route_names=("studio_route_this_site_does_not_mount",),
        order=1,
    )
    assert registry._destination_url(destination) == ""


def test_external_destination_needs_no_route():
    destination = registry.Destination(
        key="docs",
        title="API docs",
        url_name="",
        route_names=(),
        order=1,
        external_url="/api/docs/",
    )
    assert registry._destination_url(destination) == "/api/docs/"
    assert registry._is_live(destination, mounted=set()) is True


def test_route_name_for_degrades_on_an_unrouted_path():
    assert registry.route_name_for("/no/such/path/") == ""
    assert registry.route_name_for("") == ""
    assert registry.route_name_for(RequestFactory().get("/no/such/path/")) == ""


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=ALTERNATE_MOUNT_URLCONF)
def test_registration_does_not_depend_on_the_studio_mount_path():
    """A site is free to mount the Studio anywhere; destinations stay live."""

    live = {
        destination.key
        for section in registry.mounted_sections()
        for destination in section.destinations
    }
    assert "jobs" in live


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=ALTERNATE_MOUNT_URLCONF)
def test_route_names_can_be_scoped_to_the_actual_mount():
    """`urlconf_route_names` takes the prefix, so a non-default mount is reachable."""

    assert route_checks.mounted_route_names(mount="manage/") >= {"studio_dashboard"}


def test_extra_css_accepts_every_sequence_shape_a_site_may_configure():
    for configured, expected in (
        (None, ()),
        ((), ()),
        ([], ()),
        (["site/a.css"], ("site/a.css",)),
        (("site/a.css", "site/b.css"), ("site/a.css", "site/b.css")),
        # A single path as a plain string, the obvious reading of a sequence-typed
        # setting's default: treated as one item, never iterated into characters.
        ("site/studio.css", ("site/studio.css",)),
        ("", ()),
    ):
        with override_settings(COMMUNITY_BASE={"STUDIO_EXTRA_CSS": configured}):
            assert studio_filters.studio_extra_css() == expected


def test_extra_css_refuses_a_shape_that_is_not_a_string_or_sequence():
    """A dict, set or int is refused rather than iterated blind or silently dropped."""

    for configured in ({"site/a.css": True}, {"site/a.css"}, 3):
        with override_settings(COMMUNITY_BASE={"STUDIO_EXTRA_CSS": configured}):
            with pytest.raises(ImproperlyConfigured):
                studio_filters.studio_extra_css()


def test_tags_accessor_refuses_a_user_model_without_tags():
    """Loudly, so a site knows to configure `USER_TAGS_ACCESSOR` instead."""

    class UserWithoutTags:
        pass

    with pytest.raises(ImproperlyConfigured):
        user_tags.AttributeTagsAccessor().set(UserWithoutTags(), ["one"])


@pytest.mark.django_db
def test_user_search_skips_a_field_the_site_user_model_lacks(monkeypatch, django_user_model):
    """The shared user model has no `username`; another site's may have no `first_name`."""

    django_user_model.objects.create_user(email="searchable@example.com", password="x")
    monkeypatch.setattr(user_views, "SEARCH_FIELDS", ("email", "a_field_no_user_model_declares"))
    request = RequestFactory().get("/studio/users/", {"q": "searchable"})
    users, query, status, tag = user_views._filtered_users(request)
    assert [user.email for user in users] == ["searchable@example.com"]
