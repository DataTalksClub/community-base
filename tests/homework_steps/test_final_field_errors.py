"""Review form values after a final-field save fails."""

import pytest
from django.test import RequestFactory

from community_base.accounts.models import User
from community_base.homework_steps.models import HomeworkDraft
from community_base.homework_steps.services import save_final_fields
from community_base.homework_steps.types import Assignment, Eligibility, FinalField, Question
from community_base.homework_steps.views import handle_stepper

pytestmark = pytest.mark.django_db


class Adapter:
    def eligibility(self, request, assignment):
        return Eligibility(read=True, write=True, submit=True)


@pytest.fixture
def review_form():
    user = User.objects.create_user(email="review-form@example.com")
    assignment = Assignment(
        key="course:cohort:homework",
        title="Homework",
        questions=(Question("q1", "Explain", "short_text"),),
        final_fields=(FinalField("link", "Your project link", "url"),),
    )
    return user, assignment


def post_review(user, assignment, *, revision, value):
    draft = HomeworkDraft.objects.get(user=user, assignment_key=assignment.key)
    request = RequestFactory().post(
        "/homework/steps/",
        data={
            "step": "review",
            "revision": str(revision),
            "draft_token": str(draft.token),
            "intent": "save",
            "final_link": value,
        },
    )
    request.user = user
    return handle_stepper(request, assignment, Adapter())


def test_invalid_final_url_retains_attempt_without_saving(review_form):
    user, assignment = review_form
    save_final_fields(user, assignment, values={"link": "https://saved.example"}, revision=0)

    response = post_review(user, assignment, revision=1, value="not-a-url")

    assert response.status_code == 400
    assert b'name="final_link" type="url" maxlength="10000" value="not-a-url"' in response.content
    draft = HomeworkDraft.objects.get(user=user, assignment_key=assignment.key)
    assert draft.final_fields == {"link": "https://saved.example"}
    assert draft.revision == 1


def test_stale_review_revision_retains_attempt_without_saving(review_form):
    user, assignment = review_form
    save_final_fields(user, assignment, values={"link": "https://saved.example"}, revision=0)

    response = post_review(user, assignment, revision=0, value="https://attempted.example")

    assert response.status_code == 409
    assert (
        b'name="final_link" type="url" maxlength="10000" value="https://attempted.example"'
        in response.content
    )
    draft = HomeworkDraft.objects.get(user=user, assignment_key=assignment.key)
    assert draft.final_fields == {"link": "https://saved.example"}
    assert draft.revision == 1
