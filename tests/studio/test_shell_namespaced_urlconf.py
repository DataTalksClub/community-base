"""A Studio URLconf that declares `app_name`, and the same one without it.

A site whose Studio URL module sets `app_name` mounts its routes under a
namespace, so they reverse and resolve as `studio:settings`. Before this the
mounted-name set held the bare name while `reverse()` and the registration
needed the namespaced one, and no combination of the two satisfied both halves.
Every test here has a twin on `plain_site`, which mounts the same routes with no
namespace, so the namespace-free behaviour is pinned rather than assumed.
"""

from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.template.loader import render_to_string
from django.urls import resolve

from community_base.studio.registry import (
    Destination,
    Section,
    active_state,
    mounted_sections,
    register,
    route_name_for,
    section_only_routes,
    sections,
)
from community_base.studio.route_checks import (
    mounted_route_names,
    route_claims,
    route_partition_errors,
)
from community_base.studio.route_names import (
    studio_mount_prefix,
    studio_namespace,
    urlconf_route_names,
)


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


def test_a_section_only_route_names_its_namespace_in_full(namespaced_site):
    """`section_only_routes` has no destination to read a namespace from."""

    register_site_section(url_name="studio:settings", route_names=("studio:settings",))
    section_only_routes["studio:audit-list"] = "site719"

    state = active_state(shell_request("/studio/audit/"))

    assert state["active_section"] == "site719"
    assert state["active_destination"] == ""


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


@pytest.fixture
def namespaced_site_at_another_path(settings):
    settings.ROOT_URLCONF = "tests.studio.site_with_namespaced_studio_at_another_path"


@pytest.fixture
def site_at_another_path(settings):
    settings.ROOT_URLCONF = "tests.studio.site_with_studio_at_another_path"


def test_the_package_studio_mount_is_found_rather_than_assumed(namespaced_site_at_another_path):
    assert studio_mount_prefix() == "manage/"
    assert studio_namespace() == "studio"


def test_the_package_mount_defaults_are_unchanged_without_a_namespace(plain_site):
    assert studio_mount_prefix() == "studio/"
    assert studio_namespace() == ""


def test_the_shell_renders_on_a_namespaced_mount_at_another_path(
    namespaced_site_at_another_path,
):
    """The acceptance case: both adoption shapes at once, sidebar links working.

    Every one of these hrefs was a `NoReverseMatch` that took the whole page
    down, not a missing link: the shell hardcoded `studio_dashboard` and
    `studio_global_search` as bare names.
    """

    html = render_shell("/manage/")

    assert 'href="/manage/"' in html
    assert html.count('data-endpoint="/manage/search/"') == 2
    assert 'href="/manage/jobs/"' in nav_link(html, "jobs")
    assert 'href="/manage/users/"' in nav_link(html, "users")


def test_a_deep_package_route_is_active_on_a_namespaced_mount_at_another_path(
    namespaced_site_at_another_path,
):
    state = active_state(shell_request("/manage/jobs/"))

    assert state["route_name"] == "studio:community_base_jobs"
    assert state["active_destination"] == "jobs"


def test_the_route_check_passes_on_a_namespaced_mount_at_another_path(
    namespaced_site_at_another_path,
):
    assert route_partition_errors() == []
    assert mounted_route_names() >= {"studio:studio_dashboard", "studio:community_base_jobs"}


def test_the_route_check_passes_on_a_mount_at_another_path(site_at_another_path):
    """Finding 9 without the namespace: the prefix was hardcoded to `studio/`."""

    assert route_partition_errors() == []


def test_the_management_command_checks_the_mount_it_is_given(namespaced_site_at_another_path):
    stdout = StringIO()
    call_command("studio_routes", "--check", stdout=stdout)

    assert stdout.getvalue().strip() == "OK"
    with pytest.raises(CommandError):
        call_command("studio_routes", "--check", "--mount", "nowhere/", stdout=StringIO())


def test_registration_never_reads_the_urlconf(monkeypatch):
    """`AppConfig.ready()` calls `register()`, and it must not resolve URLs.

    Walking the resolver there imports the root URLconf mid-startup, before
    every app has registered what that URLconf builds itself from: the API
    endpoints registered after this app lose their routes, silently. The
    contract predates this issue; qualifying route names is what nearly broke
    it.
    """

    def refuse(*args, **kwargs):
        raise AssertionError("registration read the URLconf")

    monkeypatch.setattr("community_base.studio.route_names.get_resolver", refuse)

    register_site_section(url_name="studio:settings", route_names=("settings",))

    assert any(item.slug == "site719" for item in sections())
