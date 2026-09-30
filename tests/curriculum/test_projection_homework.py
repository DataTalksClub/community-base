"""Nested curriculum pages keep the existing cohort-owned homework destination."""

import pytest
from django.urls import include, path, reverse

from community_base.coursework.models import Submission
from community_base.curriculum.projection import CourseTree
from tests.coursework.test_models import homework, question
from tests.curriculum.test_models import make_cohort
from tests.curriculum.test_projection import mixed_course  # noqa: F401

pytestmark = pytest.mark.django_db
urlpatterns = [
    path("courses/", include("community_base.coursework.urls")),
    path("courses/", include("community_base.curriculum.urls")),
]


@pytest.fixture
def bound(mixed, settings, client, django_user_model):
    settings.ROOT_URLCONF = __name__
    course, cohort, root, first, child, nested, *_ = mixed
    assignment = homework(cohort, module=root, unit=nested, state="OP")
    item = question(
        assignment, text="Visible question", answer_type="ANY", correct_answer="HIDDEN-KEY"
    )
    user = django_user_model.objects.create_user(email="nested-homework@example.test")
    client.force_login(user)
    url = CourseTree(course).project(cohort).resolve("stored-root/repeat/welcome").url
    return cohort, nested, assignment, item, user, url


def test_nested_form_posts_to_real_cohort_handler_and_keeps_answer_private(bound, client):
    cohort, nested, assignment, item, user, url = bound
    response = client.get(url)
    assert response.status_code == 200
    action = reverse("coursework_homework", args=[cohort.course.slug, cohort.slug, assignment.slug])
    body = response.content.decode()
    assert f'action="{action}"' in body
    assert f'name="answer_{item.pk}"' in body
    assert "HIDDEN-KEY" not in body
    posted = client.post(action, {f"answer_{item.pk}": "learner response"})
    assert posted.status_code == 302
    submission = Submission.objects.get(student=user, homework=assignment)
    assert submission.answers.get().answer_text == "learner response"
    assert submission.homework.unit_id == nested.pk


def test_same_nested_unit_uses_selected_cohort_binding_only(bound, client):
    cohort, nested, assignment, item, user, url = bound
    other = make_cohort(cohort.course, slug="other", title="Other cohort")
    alternate = homework(other, unit=nested, title="Alternate assignment", state="OP")
    question(alternate, text="Alternate question")
    alternate_url = (
        CourseTree(cohort.course).project(other).resolve("stored-root/repeat/welcome").url
    )
    body = client.get(alternate_url).content.decode()
    assert "Alternate assignment" in body and "Alternate question" in body
    assert "Visible question" not in body
    assert "Alternate question" not in client.get(url).content.decode()
