from pathlib import Path

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

STUDIO_TEMPLATES = (
    "community_base/config/templates/community_base/config/settings.html",
    "community_base/api/templates/community_base/api/api_keys.html",
    "community_base/jobs/templates/community_base/jobs/jobs.html",
    "community_base/mail/templates/community_base/mail/deliveries.html",
    "community_base/mail/templates/community_base/mail/delivery_detail.html",
    "community_base/mail/templates/community_base/mail/template_list.html",
    "community_base/mail/templates/community_base/mail/template_detail.html",
)


def test_all_phase_zero_and_one_operator_templates_extend_shared_shell():
    root = Path(__file__).parents[2]

    for relative_path in STUDIO_TEMPLATES:
        first_line = (root / relative_path).read_text().splitlines()[0]
        assert first_line == '{% extends "community_base/studio/base.html" %}'


@pytest.mark.parametrize(
    ("route_name", "label", "superuser"),
    (
        ("community_base_settings", "Settings", False),
        ("community_base_api_keys", "API keys", True),
        ("community_base_jobs", "Jobs", False),
        ("community_base_mail_deliveries", "Mail", False),
    ),
)
def test_each_package_landing_page_renders_in_active_operations_shell(
    client, django_user_model, route_name, label, superuser
):
    user = django_user_model.objects.create_user(
        email=f"operator-{route_name}@example.com",
        is_staff=True,
        is_superuser=superuser,
    )
    client.force_login(user)

    response = client.get(reverse(route_name))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Operations" in content
    assert label in content
    assert content.count('aria-current="page"') == 1
