import pytest

from community_base.studio.providers import register_card_provider, register_search_provider
from community_base.studio.registry import Destination, DestinationGroup, Section, register

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_user(django_user_model):
    return django_user_model.objects.create_user(email="studio-staff@example.com", is_staff=True)


def test_staff_dashboard_renders_registered_shell(client, staff_user):
    register_card_provider("summary", lambda request: {"title": "Queue", "value": 3})
    client.force_login(staff_user)

    response = client.get("/studio/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Community Base Studio" in content
    assert "Queue" in content
    assert 'aria-current="page"' in content
    assert "Operations" in content
    assert "Settings" in content
    assert "Jobs" in content
    assert "Mail" in content


def test_superuser_dashboard_shows_api_keys(client, django_user_model):
    user = django_user_model.objects.create_superuser(email="studio-superuser@example.com")
    client.force_login(user)

    response = client.get("/studio/")

    assert response.status_code == 200
    assert "API keys" in response.content.decode()


def test_dashboard_rejects_non_staff(client, django_user_model):
    user = django_user_model.objects.create_user(email="member@example.com")
    client.force_login(user)

    assert client.get("/studio/").status_code == 403


def test_global_search_merges_registered_providers(client, staff_user):
    register_search_provider(
        "example",
        lambda request, query: {
            "records": [{"label": query, "url": "/record/1/", "type": "Record"}]
        },
    )
    client.force_login(staff_user)

    response = client.get("/studio/search/", {"q": "needle"})

    assert response.status_code == 200
    assert response.json()["results"]["records"][0]["label"] == "needle"


def test_global_search_includes_registered_navigation(client, staff_user):
    register_search_provider(
        "extra-pages",
        lambda request, query: {"pages": [{"label": "Dashboard help", "url": "/help/"}]},
    )
    client.force_login(staff_user)

    response = client.get("/studio/search/", {"q": "dash"})

    assert [item["label"] for item in response.json()["results"]["pages"]] == [
        "Dashboard",
        "Dashboard help",
    ]


def register_grouped_section(superuser_only=False):
    register(
        Section(
            "automation",
            "Automation",
            600,
            "settings",
            groups=(
                DestinationGroup(
                    key="triggers",
                    title="Triggers",
                    order=10,
                    destinations=(
                        Destination(
                            key="webhook_console",
                            title="Webhook console",
                            url_name="studio_dashboard",
                            route_names=("studio_webhook_console",),
                            order=10,
                            superuser_only=superuser_only,
                        ),
                    ),
                ),
            ),
        )
    )


def test_global_search_finds_a_destination_inside_a_group(client, staff_user):
    register_grouped_section()
    client.force_login(staff_user)

    response = client.get("/studio/search/", {"q": "webhook"})

    pages = response.json()["results"]["pages"]
    assert [item["label"] for item in pages] == ["Webhook console"]
    assert pages[0]["summary"] == "Automation · Triggers"


def test_global_search_hides_a_restricted_grouped_destination_from_staff(client, staff_user):
    register_grouped_section(superuser_only=True)
    client.force_login(staff_user)

    response = client.get("/studio/search/", {"q": "webhook"})

    assert response.json()["results"].get("pages", []) == []


def test_global_search_shows_a_restricted_grouped_destination_to_a_superuser(
    client, django_user_model
):
    register_grouped_section(superuser_only=True)
    user = django_user_model.objects.create_superuser(email="studio-superuser-search@example.com")
    client.force_login(user)

    response = client.get("/studio/search/", {"q": "webhook"})

    assert [item["label"] for item in response.json()["results"]["pages"]] == ["Webhook console"]
