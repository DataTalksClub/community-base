import uuid

import pytest
from django.core.exceptions import ValidationError
from django.test import RequestFactory

from community_base.accounts.models import User
from community_base.coursework.models import Answer, Submission
from community_base.homework_steps.coursework import CourseworkAdapter, coursework_assignment
from community_base.homework_steps.models import HomeworkDraft
from community_base.homework_steps.services import save_answer, submit_draft
from tests.coursework.test_models import coursework_cohort
from tests.coursework.test_models import homework as make_homework
from tests.coursework.test_models import question as make_question

pytestmark = pytest.mark.django_db


def _request(user):
    request = RequestFactory().post("/homework/steps/")
    request.user = user
    return request


def test_coursework_adapter_maps_stable_choices_and_calls_existing_submission_path(settings):
    submitted_events = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_HOMEWORK_SUBMITTED": lambda **event: submitted_events.append(event),
    }
    cohort = coursework_cohort()
    homework = make_homework(cohort)
    question = make_question(
        homework,
        question_type="MC",
        possible_answers="Alpha\nBeta",
        source_question_id="which",
        source_option_ids=["alpha", "beta"],
        source_content_id=uuid.uuid4(),
        source_path="courses/homework.md",
        source_commit_sha="a" * 40,
        source_checksum="b" * 64,
        correct_answer="2",
    )
    user = User.objects.create_user(email="adapter@example.com")
    assignment = coursework_assignment(homework, user)
    adapter = CourseworkAdapter(homework)

    assert assignment.key == f"coursework:{cohort.pk}:{homework.pk}"
    draft = save_answer(user, assignment, question_key="which", answer="beta", revision=0)
    assert Submission.objects.count() == 0
    assert Answer.objects.count() == 0
    assert submitted_events == []

    result = submit_draft(
        _request(user), assignment, adapter, revision=draft.revision, token=draft.token
    )

    assert result.pk == Submission.objects.get(homework=homework, student=user).pk
    assert Answer.objects.get(question=question).answer_text == "2"
    assert submitted_events == [{"submission": result}]
    assert not HomeworkDraft.objects.filter(user=user, assignment_key=assignment.key).exists()
    edited = coursework_assignment(homework, user)
    assert edited.existing_answers == {"which": "beta"}
    assert edited.has_submission is True
    assert edited.availability == "open"
    assert edited.accepted_submission.submitted_at == result.submitted_at


def test_coursework_closure_retains_draft_and_does_not_submit():
    cohort = coursework_cohort()
    homework = make_homework(cohort)
    question = make_question(homework, text="Explain", answer_type="ANY")
    user = User.objects.create_user(email="closed-adapter@example.com")
    assignment = coursework_assignment(homework, user)
    adapter = CourseworkAdapter(homework)
    draft = save_answer(
        user, assignment, question_key=f"db-{question.pk}", answer="Explanation", revision=0
    )
    homework.state = "CL"
    homework.save(update_fields=["state"])

    closed_assignment = coursework_assignment(homework, user)
    assert closed_assignment.availability == "closed"
    assert adapter.eligibility(_request(user), closed_assignment).submit is False
    with pytest.raises(ValidationError, match="closed"):
        submit_draft(
            _request(user),
            closed_assignment,
            adapter,
            revision=draft.revision,
            token=draft.token,
        )
    assert HomeworkDraft.objects.filter(user=user, assignment_key=assignment.key).exists()
    assert Submission.objects.count() == 0
