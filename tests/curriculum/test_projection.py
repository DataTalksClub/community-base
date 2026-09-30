"""Mixed destinations, cohort scope and batched curriculum traversal."""

import pytest
from django.http import Http404

from community_base.curriculum.models import CohortModule
from community_base.curriculum.projection import CourseTree
from community_base.curriculum.services import ensure_enrollment, mark_completed
from tests.curriculum.test_models import make_cohort, make_course, make_module, make_unit

pytestmark = pytest.mark.django_db


@pytest.fixture(name="mixed")
def mixed_course():
    course = make_course()
    cohort = make_cohort(course, mode="self_paced")
    root = make_module(course, slug="stored-root", title="Root")
    first = make_unit(root, slug="first", title="First", source_sibling_position=0, sort_order=99)
    child = make_module(
        course,
        parent=root,
        slug="repeat",
        title="Child",
        source_sibling_position=1,
        is_bonus=True,
        syllabus_section="Authored section",
    )
    nested = make_unit(child, title="Nested", body="Nested **lesson**.")
    last = make_unit(root, slug="last", title="Last", source_sibling_position=2, sort_order=-1)
    other = make_module(course, slug="other", title="Other", sort_order=2)
    repeated = make_module(course, parent=other, slug="repeat", title="Repeated child")
    repeated_unit = make_unit(repeated, title="Other nested", body="Other body.")
    return course, cohort, root, first, child, nested, last, other, repeated_unit


def test_one_projection_preserves_order_ancestors_metadata_and_destinations(mixed, client):
    course, cohort, root, first, child, nested, last, other, repeated = mixed
    projection = CourseTree(course).project(cohort)
    assert [row.item for row in projection.units] == [first, nested, last, repeated]
    assert [row.item for row in projection.roots[0].children] == [first, child, last]
    nested_row = projection.resolve("stored-root/repeat/welcome")
    assert [row.item for row in nested_row.ancestors] == [root, child]
    assert nested_row.item.effective_is_bonus is True
    assert nested_row.ancestors[-1].item.syllabus_section == "Authored section"
    assert projection.resolve("other/repeat/welcome").item == repeated
    for row in projection.entries:
        response = client.get(row.url)
        assert response.status_code == 200
        assert f'<h1 class="cb-page-title">{row.item.title}</h1>' in response.content.decode()
    assert root.slug == "stored-root"


def test_course_module_sidebar_breadcrumbs_and_navigation_use_same_order(
    mixed, client, django_user_model
):
    course, cohort, root, first, child, nested, last, other, repeated = mixed
    user = django_user_model.objects.create_user(email="mixed@example.test")
    ensure_enrollment(user, cohort)
    mark_completed(user, first, cohort=cohort)
    client.force_login(user)
    projection = CourseTree(course).project(cohort)
    response = client.get(f"/courses/{course.slug}/")
    assert response.status_code == 200
    body = response.content.decode()
    assert f'href="{projection.resolve("stored-root/repeat/welcome").url}">Continue</a>' in body
    syllabus = body[body.index('aria-label="Cohorts"') :]
    assert syllabus.index(">First</a>") < syllabus.index(">Child</a>") < syllabus.index(">Last</a>")
    response = client.get(projection.resolve("stored-root/repeat/welcome").url)
    body = response.content.decode()
    assert "Nested <strong>lesson</strong>." in body
    assert "Previous: First" in body and "Next: Last" in body
    assert "<strong>Nested</strong>" in body
    assert f'href="{projection.resolve("stored-root").url}">Root</a>' in body
    assert f'href="{projection.resolve("stored-root/repeat").url}">Child</a>' in body


def test_placements_curate_syllabus_without_restricting_reader_navigation(
    mixed, client, django_user_model
):
    course, cohort, root, first, child, nested, last, other, repeated = mixed
    CohortModule.objects.create(cohort=cohort, module=other, sort_order=0)
    projection = CourseTree(course).project(cohort)
    assert [row.item for row in projection.units] == [repeated]
    with pytest.raises(Http404):
        projection.resolve("stored-root/repeat/welcome")
    reader = CourseTree(course).project(cohort, use_placements=False)
    assert client.get(reader.resolve("stored-root/repeat/welcome").url).status_code == 200
    user = django_user_model.objects.create_user(email="curated@example.test")
    ensure_enrollment(user, cohort)
    client.force_login(user)
    response = client.get(f"/courses/{course.slug}/")
    assert f'href="{reader.units[0].url}">Continue</a>' in response.content.decode()
    assert "Previous: Last" in client.get(projection.units[0].url).content.decode()


def test_projection_queries_do_not_grow_with_tree_size(mixed, django_assert_num_queries):
    course, cohort, *_ = mixed
    with django_assert_num_queries(3):
        projection = CourseTree(course).project(cohort)
        for node in projection.entries:
            assert node.item.effective_is_bonus in (True, False)
            if not node.is_module:
                assert node.item.effective_required_level == 0
                assert node.item.effective_available_after_days is None
    for index in range(12):
        root = make_module(course, slug=f"extra-{index}")
        child = make_module(course, parent=root, slug="child")
        make_unit(child)
    with django_assert_num_queries(3):
        assert len(CourseTree(course).project(cohort).units) == 16


def test_caller_owns_urls_and_legacy_none_order_stays_stable(mixed):
    course, cohort, root, first, child, nested, last, other, repeated = mixed
    projection = CourseTree(course).project(
        cohort, lambda course, cohort, item, path: "/host/" + "/".join(path)
    )
    assert (
        projection.resolve("stored-root/repeat/welcome").url == "/host/stored-root/repeat/welcome"
    )
    for item in (first, last, child):
        item.source_sibling_position = None
        item.save()
    assert CourseTree(course).ordered_units() == [last, first, nested, repeated]


def test_nested_destinations_remain_course_scoped_and_integer_endpoint_is_json(mixed, client):
    course, cohort, root, first, child, nested, *_ = mixed
    other = make_course(slug="unrelated")
    make_cohort(other, slug=cohort.slug)
    assert (
        client.get(
            f"/courses/unrelated/cohorts/{cohort.slug}/curriculum/stored-root/repeat/welcome/"
        ).status_code
        == 404
    )
    response = client.get(f"/courses/{course.slug}/units/{nested.pk}/")
    assert response.status_code == 200
    assert response.json()["id"] == nested.pk
    assert client.get(f"/courses/unrelated/units/{nested.pk}/").status_code == 404


def test_nested_api_siblings_have_exact_order_metadata_and_working_destinations(mixed, client):
    course, cohort, root, first, child, nested, last, *_ = mixed
    response = client.get(f"/courses/api/courses/{course.slug}/")
    assert response.status_code == 200
    modules = response.json()["syllabus"][0]["modules"]
    siblings = modules[0]["siblings"]
    assert [(row["type"], row["id"]) for row in siblings] == [
        ("unit", first.pk),
        ("module", child.pk),
        ("unit", last.pk),
    ]
    assert siblings[1]["syllabus_section"] == "Authored section"
    assert siblings[1]["is_bonus"] is True
    nested_payload = modules[0]["children"][0]["siblings"][0]
    assert nested_payload["id"] == nested.pk
    for row in [*siblings, nested_payload]:
        result = client.get(row["public_url"])
        assert result.status_code == 200
        assert f'<h1 class="cb-page-title">{row["title"]}</h1>' in result.content.decode()
    assert "body" not in nested_payload and "correct" not in str(response.json())


def test_nested_preview_and_gate_keep_body_private(mixed, client):
    course, cohort, root, first, child, nested, *_ = mixed
    course.required_level = 20
    course.save()
    url = CourseTree(course).project(cohort).resolve("stored-root/repeat/welcome").url
    response = client.get(url)
    assert response.status_code == 403
    assert "Sign in to read this lesson" in response.content.decode()
    assert "Nested <strong>lesson</strong>." not in response.content.decode()
    nested.is_preview = True
    nested.save()
    response = client.get(url)
    assert response.status_code == 200
    assert "Nested <strong>lesson</strong>." in response.content.decode()


def test_nested_drip_inherits_parent_and_completion_stays_same_identity(
    mixed, client, django_user_model
):
    from django.utils import timezone

    from community_base.curriculum.models import UnitProgress

    course, cohort, root, first, child, nested, *_ = mixed
    user = django_user_model.objects.create_user(email="drip-mixed@example.test")
    ensure_enrollment(user, cohort)
    client.force_login(user)
    cohort.mode, cohort.start_date = "cohort", timezone.now().date()
    cohort.save()
    root.available_after_days = 7
    root.save()
    url = CourseTree(course).project(cohort).resolve("stored-root/repeat/welcome").url
    response = client.get(url)
    assert response.status_code == 403
    assert "This lesson opens on" in response.content.decode()
    root.available_after_days = None
    root.save()
    assert client.get(url).status_code == 200
    assert client.post(f"/courses/{course.slug}/units/{nested.pk}/complete/").json() == {
        "completed": True
    }
    assert UnitProgress.objects.get(user=user).unit_id == nested.pk
    assert "Completed" in client.get(url).content.decode()


def test_studio_addition_does_not_displace_authored_mixed_order(mixed):
    course, cohort, root, first, child, nested, last, other, repeated = mixed
    extra = make_unit(root, slug="manual", title="Manual", sort_order=-100)
    projection = CourseTree(course).project(cohort)
    assert [row.item for row in projection.units] == [first, nested, last, extra, repeated]


def test_module_overview_and_sidebar_preserve_mixed_rendered_order(mixed, client):
    course, cohort, root, *_ = mixed
    projection = CourseTree(course).project(cohort)
    overview = client.get(projection.resolve("stored-root").url).content.decode()
    assert overview.index(">First</a>") < overview.index(">Child</a>") < overview.index(">Last</a>")
    body = client.get(projection.resolve("stored-root/repeat/welcome").url).content.decode()
    sidebar = body[body.index("cb-unit-sidebar") :]
    assert sidebar.index(">First</a>") < sidebar.index(">Child</a>")
    assert (
        sidebar.index(">Child</a>") < sidebar.index(">Nested</strong>") < sidebar.index(">Last</a>")
    )


def test_hidden_cohort_and_unpublished_course_do_not_expose_nested_destinations(mixed, client):
    course, cohort, *_ = mixed
    url = CourseTree(course).project(cohort).resolve("stored-root/repeat/welcome").url
    cohort.visible = False
    cohort.save()
    assert client.get(url).status_code == 404
    cohort.visible = True
    cohort.save()
    course.status = "draft"
    course.save()
    assert client.get(url).status_code == 404
