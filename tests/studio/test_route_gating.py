"""Studio destinations follow the routes a site mounts, not the apps it installs."""

from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import call_command

from community_base.studio import registry
from community_base.studio.registry import Destination, Section, active_state, mounted_sections
from community_base.studio.route_checks import route_claims, route_partition_errors

OPTIONAL_ROUTES = (
    "community_base_mail_deliveries",
    "community_base_mail_delivery",
    "community_base_mail_template",
    "community_base_mail_templates",
    "knowledge_base_studio_page_detail",
    "knowledge_base_studio_page_list",
)


@pytest.fixture
def without_optional_studio_urls(settings):
    settings.ROOT_URLCONF = "tests.studio.site_without_optional_studio_urls"


@pytest.fixture
def with_optional_studio_urls(settings):
    settings.ROOT_URLCONF = "tests.studio.site_with_optional_studio_urls"


def staff_request(route_name="studio_dashboard"):
    return SimpleNamespace(
        resolver_match=SimpleNamespace(url_name=route_name),
        user=SimpleNamespace(is_superuser=True),
    )


def destination_keys(sections):
    keys = []
    for section in sections:
        keys.extend(item.key for item in section.destinations)
        for group in section.groups:
            keys.extend(item.key for item in group.destinations)
    return keys


def test_unmounted_app_routes_are_not_claimed(without_optional_studio_urls):
    claims = route_claims()

    assert [route for route in OPTIONAL_ROUTES if route in claims] == []


def test_the_route_check_passes_without_the_optional_mounts(without_optional_studio_urls):
    assert route_partition_errors() == []


def test_the_management_command_passes_without_the_optional_mounts(without_optional_studio_urls):
    stdout = StringIO()

    call_command("studio_routes", "--check", stdout=stdout)

    assert stdout.getvalue().strip() == "OK"


def test_unmounted_destinations_leave_the_shell(without_optional_studio_urls):
    state = active_state(staff_request())

    slugs = [row["section"].slug for row in state["sections"]]
    assert slugs == ["home", "people"]
    assert destination_keys(mounted_sections()) == ["dashboard", "users"]


def test_mounted_routes_claim_their_destinations(with_optional_studio_urls):
    claims = route_claims()

    assert [claims.get(route) for route in OPTIONAL_ROUTES] == [
        ["destination:operations/mail"],
        ["destination:operations/mail"],
        ["destination:operations/mail"],
        ["destination:operations/mail"],
        ["destination:knowledge-base/knowledge-base-pages"],
        ["destination:knowledge-base/knowledge-base-pages"],
    ]
    assert route_partition_errors() == []


def test_mounted_destinations_render_in_the_shell(with_optional_studio_urls):
    state = active_state(staff_request())

    slugs = [row["section"].slug for row in state["sections"]]
    assert slugs == ["home", "people", "knowledge-base", "operations"]
    assert destination_keys(mounted_sections()) == [
        "dashboard",
        "users",
        "knowledge-base-pages",
        "mail",
    ]


def test_every_package_destination_survives_the_fully_mounted_site():
    claims = route_claims()

    assert [route for route in OPTIONAL_ROUTES if route not in claims] == []
    assert route_partition_errors() == []


def test_a_destination_without_a_mounted_home_leaves_its_deep_routes_unclaimed(
    with_optional_studio_urls,
):
    registry._clear()
    registry.register(
        Section(
            slug="operations",
            title="Operations",
            order=80,
            icon="settings",
            destinations=(
                Destination(
                    key="mail",
                    title="Mail",
                    url_name="community_base_mail_deliverie",
                    route_names=("community_base_mail_delivery",),
                    order=40,
                ),
            ),
        )
    )

    assert "community_base_mail_delivery: mounted but unclaimed" in route_partition_errors()


def test_an_external_destination_survives_the_mounted_route_filter():
    """A link that points off the URLconf has no route to mount, so it stays live.

    C7.13 keeps a destination only when its home route is mounted, and C7.14 added
    destinations whose link is an ``external_url`` and whose ``url_name`` is empty
    by design. Read naively together, the first drops every one of the second: the
    three C7.14 shell tests for icons and external links failed exactly this way
    when the two branches first met. The rule is that an external destination is
    always live, because there is nothing for the site to mount.
    """

    registry._clear()
    registry.register(
        Section(
            slug="operations",
            title="Operations",
            order=80,
            icon="settings",
            destinations=(
                Destination(
                    key="api-docs",
                    title="API docs",
                    url_name="",
                    route_names=(),
                    order=10,
                    external_url="/api/docs",
                    new_tab=True,
                ),
                Destination(
                    key="unmounted",
                    title="Unmounted",
                    url_name="a_route_this_site_does_not_mount",
                    route_names=(),
                    order=20,
                ),
            ),
        )
    )

    live = registry.mounted_sections()

    kept = [item.key for section in live for item in section.destinations]
    assert "api-docs" in kept
    assert "unmounted" not in kept
