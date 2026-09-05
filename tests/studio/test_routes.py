from types import SimpleNamespace

from community_base.studio.registry import active_state, routes_without_home
from community_base.studio.route_checks import (
    mounted_route_names,
    route_claims,
    route_partition_errors,
)


def request_for(route_name, *, superuser=False):
    return SimpleNamespace(
        resolver_match=SimpleNamespace(url_name=route_name),
        user=SimpleNamespace(is_superuser=superuser),
    )


def test_mounted_studio_routes_are_partitioned_exactly_once():
    assert route_partition_errors() == []
    assert mounted_route_names() == set(route_claims())
    assert all(len(owners) == 1 for owners in route_claims().values())


def test_partition_reports_an_unclaimed_mounted_route():
    routes_without_home.remove("studio_global_search")

    assert "studio_global_search: mounted but unclaimed" in route_partition_errors()


def test_deep_routes_activate_each_package_destination():
    cases = (
        ("community_base_settings_save_group", "settings", False),
        ("community_base_api_key_revoke", "api_keys", True),
        ("community_base_job_retry", "jobs", False),
        ("community_base_mail_delivery", "mail", False),
        ("community_base_content_sync_history", "content_sync", False),
    )

    for route_name, destination, superuser in cases:
        state = active_state(request_for(route_name, superuser=superuser))
        assert state["active_section"] == "operations"
        assert state["active_destination"] == destination

    onboarding = active_state(request_for("onboarding_studio_progress_list"))
    assert onboarding["active_section"] == "onboarding"
    assert onboarding["active_destination"] == "onboarding-flows"
