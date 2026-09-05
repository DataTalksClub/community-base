from types import SimpleNamespace

from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from community_base.kernel.decorators import staff_required, superuser_required


def view(request):
    return HttpResponse("ok")


@override_settings(LOGIN_URL="/sign-in/")
def test_staff_required_uses_configured_login_url():
    request = RequestFactory().get("/studio/", {"page": 2})
    request.user = SimpleNamespace(is_authenticated=False)

    response = staff_required(view)(request)

    assert response.status_code == 302
    assert response.url == "/sign-in/?next=/studio/%3Fpage%3D2"


def test_staff_required_forbids_non_staff_and_allows_staff():
    request = RequestFactory().get("/studio/")
    request.user = SimpleNamespace(is_authenticated=True, is_staff=False)
    assert staff_required(view)(request).status_code == 403

    request.user.is_staff = True
    assert staff_required(view)(request).content == b"ok"


def test_superuser_required_forbids_staff_and_allows_superuser():
    request = RequestFactory().get("/studio/")
    request.user = SimpleNamespace(is_authenticated=True, is_superuser=False)
    assert superuser_required(view)(request).status_code == 403

    request.user.is_superuser = True
    assert superuser_required(view)(request).content == b"ok"
