"""A Studio URLconf that declares `app_name`, and the same one without it.

A site whose Studio URL module sets `app_name` mounts its routes under a
namespace, so they reverse and resolve as `studio:settings`. Before this the
mounted-name set held the bare name while `reverse()` and the registration
needed the namespaced one, and no combination of the two satisfied both halves.
Every test here has a twin on `plain_site`, which mounts the same routes with no
namespace, so the namespace-free behaviour is pinned rather than assumed.
"""

from types import SimpleNamespace

import pytest
from django.template.loader import render_to_string
from django.urls import resolve

from community_base.studio.registry import (
    Destination,
    Section,
    active_state,
    mounted_sections,
    register,
    route_name_for,
)
from community_base.studio.route_checks import route_claims
from community_base.studio.route_names import urlconf_route_names


@pytest.fixture
def namespaced_site(settings):
    settings.ROOT_URLCONF = "tests.studio.site_with_namespaced_studio_urls"


@pytest.fixture
def plain_site(settings):
    settings.ROOT_URLCONF = "tests.studio.site_with_plain_studio_urls"


@pytest.fixture
def nested_namespaced_site(settings):
    settings.ROOT_URLCONF = "tests.studio.site_with_nested_namespaced_studio_urls"


def register_site_section(*, url_name, route_names=()):
    register(
        Section(
            "site719",
            "Site",
            90,
            "settings",
            (
                Destination(
                    key="site_settings",
                    title="Site settings",
                    url_name=url_name,
                    route_names=route_names,
                    order=10,
                ),
                Destination(
                    key="api_docs",
                    title="API docs",
                    url_name="",
                    route_names=(),
                    order=20,
                    external_url="/api/docs",
                    new_tab=True,
                ),
            ),
        )
    )


def shell_request(path="/studio/"):
    return SimpleNamespace(
        resolver_match=resolve(path),
        user=SimpleNamespace(is_superuser=True),
        session={},
    )


def render_shell(path="/studio/"):
    return render_to_string("community_base/studio/base.html", {"request": shell_request(path)})


def nav_link(html, key):
    marker = f'data-testid="studio-nav-{key}"'
    before, after = html.split(marker, 1)
    return before.rsplit("<li>", 1)[1] + marker + after.split("</li>", 1)[0]


def site_section():
    return next(item for item in mounted_sections() if item.slug == "site719")


SITE_ROUTES = ("home", "settings", "audit-list", "audit-detail")


def test_a_namespaced_urlconf_reports_the_names_reverse_takes(namespaced_site):
    mounted = urlconf_route_names()

    assert {f"studio:{name}" for name in SITE_ROUTES} <= mounted
    assert set(SITE_ROUTES).isdisjoint(mounted)
    assert "studio_dashboard" in mounted


def test_the_same_routes_without_a_namespace_are_unchanged(plain_site):
    mounted = urlconf_route_names()

    assert set(SITE_ROUTES) <= mounted
    assert [name for name in mounted if ":" in name] == []
    assert "studio_dashboard" in mounted


def test_nested_namespaces_are_joined_in_mount_order(nested_namespaced_site):
    mounted = urlconf_route_names()

    assert "ops:studio:audit-detail" in mounted
    assert "studio:audit-detail" not in mounted


def test_the_path_prefix_still_selects_by_path_under_a_namespace(namespaced_site):
    assert urlconf_route_names(prefix="studio/audit/") == {
        "studio:audit-list",
        "studio:audit-detail",
    }


def test_a_namespaced_destination_is_live_and_links_to_its_route(namespaced_site):
    register_site_section(url_name="studio:settings", route_names=("studio:settings",))

    assert [item.key for item in site_section().destinations] == ["site_settings", "api_docs"]
    assert 'href="/studio/settings/"' in nav_link(render_shell(), "site_settings")


def test_the_same_destination_without_a_namespace_is_live_and_links_to_its_route(plain_site):
    register_site_section(url_name="settings", route_names=("settings",))

    assert [item.key for item in site_section().destinations] == ["site_settings", "api_docs"]
    assert 'href="/studio/settings/"' in nav_link(render_shell(), "site_settings")


def test_a_deep_namespaced_route_marks_its_destination_active(namespaced_site):
    register_site_section(
        url_name="studio:settings", route_names=("studio:settings", "studio:audit-detail")
    )

    state = active_state(shell_request("/studio/audit/7/"))

    assert state["route_name"] == "studio:audit-detail"
    assert state["active_destination"] == "site_settings"
    assert 'aria-current="page"' in nav_link(render_shell("/studio/audit/7/"), "site_settings")


def test_a_deep_route_without_a_namespace_marks_its_destination_active(plain_site):
    register_site_section(url_name="settings", route_names=("settings", "audit-detail"))

    state = active_state(shell_request("/studio/audit/7/"))

    assert state["route_name"] == "audit-detail"
    assert state["active_destination"] == "site_settings"
    assert 'aria-current="page"' in nav_link(render_shell("/studio/audit/7/"), "site_settings")


def test_bare_route_names_keep_matching_under_the_destination_namespace(namespaced_site):
    register_site_section(url_name="studio:settings", route_names=("settings", "audit-detail"))

    state = active_state(shell_request("/studio/audit/7/"))

    assert state["active_destination"] == "site_settings"
    assert "studio:audit-detail" in route_claims()
    assert "audit-detail" not in route_claims()


def test_a_bare_url_name_is_not_live_on_a_namespaced_mount(namespaced_site):
    """`url_name` is strict: it is the spelling `reverse()` takes, or nothing.

    Admitting the bare name here is what produced an empty href. The external
    destination stays, so the section survives without its broken link.
    """

    register_site_section(url_name="settings", route_names=("settings",))

    assert [item.key for item in site_section().destinations] == ["api_docs"]


@pytest.mark.parametrize(
    ("site", "url_name"),
    (("namespaced_site", "studio:settings"), ("plain_site", "settings")),
)
def test_an_external_destination_stays_live_either_way(site, url_name, request):
    request.getfixturevalue(site)
    register_site_section(url_name=url_name)

    assert "api_docs" in [item.key for item in site_section().destinations]
    assert 'href="/api/docs"' in nav_link(render_shell(), "api_docs")


@pytest.mark.parametrize("site", ("namespaced_site", "plain_site"))
def test_an_unnamed_route_still_resolves_to_no_route_name(site, request):
    request.getfixturevalue(site)

    assert route_name_for("/studio/unnamed/") == ""
    assert route_name_for(shell_request("/studio/unnamed/")) == ""
