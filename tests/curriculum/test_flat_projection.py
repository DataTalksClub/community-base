"""Flat public rendering captured before the mixed-tree implementation."""

import json
import re
from pathlib import Path

import pytest

from community_base.curriculum.services import ensure_enrollment, mark_completed
from tests.curriculum.test_models import make_cohort, make_course, make_module, make_unit

pytestmark = pytest.mark.django_db
SNAPSHOT = Path(__file__).parent / "fixtures" / "flat_projection.json"


def flat_setup(user):
    course = make_course(pk=11, description="Flat **description**.")
    cohort = make_cohort(course, pk=41, mode="self_paced")
    module = make_module(course, pk=21, overview="Module **overview**.")
    first = make_unit(module, pk=31, body="First **body**.", is_preview=True)
    make_unit(module, pk=32, slug="last", title="Last", sort_order=2, homework="Exercise.")
    ensure_enrollment(user, cohort)
    mark_completed(user, first, cohort=cohort)
    return course


def normalized_response(response):
    if response.headers["Content-Type"].startswith("application/json"):
        return {"status": response.status_code, "json": response.json()}
    main = re.search(r"<main\b.*?</main>", response.content.decode(), re.S).group()
    main = re.sub(
        r'name="csrfmiddlewaretoken" value="[^"]+"',
        'name="csrfmiddlewaretoken" value="TOKEN"',
        main,
    )
    return {"status": response.status_code, "html": re.sub(r">\s+<", "><", main).strip()}


def flat_responses(client, django_user_model):
    user = django_user_model.objects.create_user(email="flat@example.test")
    course = flat_setup(user)
    paths = [
        "/courses/test-course/",
        "/courses/test-course/2026/intro/",
        "/courses/test-course/2026/intro/welcome/",
        "/courses/test-course/2026/intro/last/",
        "/courses/api/courses/test-course/",
        "/courses/test-course/units/31/",
    ]
    result = {}
    for path in paths:
        result["anonymous:" + path] = normalized_response(client.get(path))
    client.force_login(user)
    for path in paths:
        result["member:" + path] = normalized_response(client.get(path))
    course.required_level = 20
    course.save()
    client.logout()
    for slug in ("last", "welcome"):
        result["gated:" + slug] = normalized_response(
            client.get(f"/courses/test-course/2026/intro/{slug}/")
        )
    return result


def test_flat_rendering_and_json_match_before_output(client, django_user_model):
    assert flat_responses(client, django_user_model) == json.loads(SNAPSHOT.read_text())


def curated_responses(client, django_user_model, placement):
    from community_base.curriculum.models import CohortModule

    user = django_user_model.objects.create_user(email="curated-flat@example.test")
    course = flat_setup(user)
    cohort = course.cohorts.get()
    first = course.modules.get()
    second = make_module(course, pk=22, slug="second", title="Second", sort_order=2)
    make_unit(second, pk=33, slug="other", title="Other")
    CohortModule.objects.create(cohort=cohort, module=second, sort_order=0)
    if placement == "reordered":
        CohortModule.objects.create(cohort=cohort, module=first, sort_order=1)
    client.force_login(user)
    paths = [
        "/courses/test-course/",
        "/courses/test-course/2026/intro/",
        "/courses/test-course/2026/intro/last/",
        "/courses/test-course/2026/second/other/",
        "/courses/api/courses/test-course/",
    ]
    return {path: normalized_response(client.get(path)) for path in paths}


@pytest.mark.parametrize("placement", ["subset", "reordered"])
def test_flat_curated_cohorts_keep_reader_navigation_global(client, django_user_model, placement):
    expected = SNAPSHOT.with_name(f"flat_{placement}_projection.json")
    assert curated_responses(client, django_user_model, placement) == json.loads(
        expected.read_text()
    )
