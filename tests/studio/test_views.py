import pytest

from community_base.studio.providers import register_card_provider, register_search_provider

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_user(django_user_model):
    return django_user_model.objects.create_user(username="studio-staff", is_staff=True)


def test_staff_dashboard_renders_registered_shell(client, staff_user):
    register_card_provider("summary", lambda request: {"title": "Queue", "value": 3})
    client.force_login(staff_user)

    response = client.get("/studio/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Community Base Studio" in content
    assert "Queue" in content
    assert 'aria-current="page"' in content


def test_dashboard_rejects_non_staff(client, django_user_model):
    user = django_user_model.objects.create_user(username="member")
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
    client.force_login(staff_user)

    response = client.get("/studio/search/", {"q": "dash"})

    assert response.json()["results"]["pages"][0]["label"] == "Dashboard"
