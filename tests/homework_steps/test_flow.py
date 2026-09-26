from datetime import UTC, datetime
from html.parser import HTMLParser

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.test import RequestFactory

from community_base.accounts.models import User
from community_base.homework_steps.models import HomeworkDraft
from community_base.homework_steps.services import clear_draft, save_answer, save_final_fields
from community_base.homework_steps.state import homework_state_for
from community_base.homework_steps.types import (
    AcceptedSubmission,
    Assignment,
    Eligibility,
    FinalField,
    Option,
    Question,
)
from community_base.homework_steps.views import handle_stepper

pytestmark = pytest.mark.django_db


class StepperStateParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._capture_status = False
        self._capture_current_step = False
        self.status_messages = []
        self.current_step = ""
        self.homework_state = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "data-homework-state" in attributes:
            self.homework_state = (
                attributes["data-homework-state"],
                attributes["aria-label"],
            )
        self._capture_status = tag == "p" and attributes.get("role") == "status"
        self._capture_current_step = tag == "a" and attributes.get("aria-current") == "step"

    def handle_data(self, data):
        if self._capture_status:
            self.status_messages.append(data.strip())
        if self._capture_current_step:
            self.current_step += data.strip()

    def handle_endtag(self, tag):
        if tag == "p":
            self._capture_status = False
        if tag == "a":
            self._capture_current_step = False


class Adapter:
    def __init__(self):
        self.policy = Eligibility(read=True, write=True, submit=True)
        self.submissions = []
        self.fail = False

    def eligibility(self, request, assignment):
        return self.policy

    def submit(self, request, assignment, answers, final_fields):
        self.submissions.append((answers, final_fields))
        if self.fail:
            raise ValidationError("Host rejected submission")
        return object()


@pytest.fixture
def user():
    return User.objects.create_user(email="homework-steps@example.com")


@pytest.fixture
def assignment():
    return Assignment(
        key="course:cohort-1:homework-1",
        title="Homework one",
        questions=(
            Question("q1", "Choose one", "choice", (Option("a", "Alpha"), Option("b", "Beta"))),
            Question("q2", "Explain", "long_text"),
        ),
        final_fields=(FinalField("link", "Your project link", "url"),),
    )


def request(user, *, method="GET", data=None, query=""):
    factory = RequestFactory()
    url = f"/homework/steps/{query}"
    result = factory.post(url, data=data or {}) if method == "POST" else factory.get(url)
    result.user = user
    return result


def flow(user, assignment, adapter, *, method="GET", data=None, query=""):
    data = dict(data or {})
    if method == "POST" and "draft_token" not in data:
        data["draft_token"] = str(
            HomeworkDraft.objects.get(user=user, assignment_key=assignment.key).token
        )
    return handle_stepper(
        request(user, method=method, data=data, query=query),
        assignment,
        adapter,
        step_param="homework_step",
        query_params={"cohort": "cohort-1"},
    )


def test_save_resume_reorder_and_second_session(user, assignment):
    adapter = Adapter()
    first = flow(user, assignment, adapter, query="?homework_step=q1")
    assert first.status_code == 200
    saved = flow(
        user,
        assignment,
        adapter,
        method="POST",
        data={"homework_step": "q1", "revision": "0", "answer": "b", "next_step": "q2"},
    )
    assert saved.status_code == 302
    assert saved["Location"] == "/homework/steps/?cohort=cohort-1&homework_step=q2"
    assert adapter.submissions == []
    reordered = Assignment(
        key=assignment.key,
        title=assignment.title,
        questions=tuple(reversed(assignment.questions)),
        final_fields=assignment.final_fields,
    )
    resumed = flow(user, reordered, adapter, query="?homework_step=q1")
    assert b'value="b" checked' in resumed.content
    assert HomeworkDraft.objects.get(user=user, assignment_key=assignment.key).answers == {
        "q1": "b"
    }


def test_stale_revision_preserves_saved_answer_and_typed_value(user, assignment):
    adapter = Adapter()
    flow(user, assignment, adapter)
    response = flow(
        user,
        assignment,
        adapter,
        method="POST",
        data={
            "homework_step": "q1",
            "revision": "0",
            "answer": "a",
        },
    )
    assert response.status_code == 302
    conflict = flow(
        user,
        assignment,
        adapter,
        method="POST",
        data={
            "homework_step": "q1",
            "revision": "0",
            "answer": "b",
        },
    )
    assert conflict.status_code == 409
    assert b'value="b" checked' in conflict.content
    assert HomeworkDraft.objects.get(user=user, assignment_key=assignment.key).answers == {
        "q1": "a"
    }


def test_final_handoff_uses_latest_answers_and_retains_failed_draft(user, assignment):
    adapter = Adapter()
    flow(user, assignment, adapter)
    flow(
        user,
        assignment,
        adapter,
        method="POST",
        data={
            "homework_step": "q1",
            "revision": "0",
            "answer": "a",
        },
    )
    flow(
        user,
        assignment,
        adapter,
        method="POST",
        data={
            "homework_step": "q2",
            "revision": "1",
            "answer": "Long answer",
        },
    )
    adapter.fail = True
    failed = flow(
        user,
        assignment,
        adapter,
        method="POST",
        data={
            "homework_step": "review",
            "revision": "2",
            "intent": "submit",
            "final_link": "https://example.com/project",
        },
    )
    assert failed.status_code == 400
    draft = HomeworkDraft.objects.get(user=user, assignment_key=assignment.key)
    assert draft.final_fields == {"link": "https://example.com/project"}
    adapter.fail = False
    accepted = flow(
        user,
        assignment,
        adapter,
        method="POST",
        data={
            "homework_step": "review",
            "revision": str(draft.revision),
            "intent": "submit",
            "final_link": "https://example.com/project",
        },
    )
    assert accepted.status_code == 302
    assert adapter.submissions[-1] == (
        {"q1": "a", "q2": "Long answer"},
        {"link": "https://example.com/project"},
    )
    assert not HomeworkDraft.objects.filter(user=user, assignment_key=assignment.key).exists()


def test_invalid_keys_closed_policy_and_other_user_are_rejected(user, assignment):
    adapter = Adapter()
    flow(user, assignment, adapter)
    invalid = flow(
        user,
        assignment,
        adapter,
        method="POST",
        data={
            "homework_step": "other",
            "revision": "0",
            "answer": "x",
        },
    )
    assert invalid.status_code == 400
    forged = flow(
        user,
        assignment,
        adapter,
        method="POST",
        data={
            "homework_step": "q1",
            "assignment_key": "other",
            "revision": "0",
            "answer": "a",
        },
    )
    assert forged.status_code == 400
    adapter.policy = Eligibility(True, False, False, "Closed")
    closed = flow(
        user,
        assignment,
        adapter,
        method="POST",
        data={
            "homework_step": "q1",
            "revision": "0",
            "answer": "a",
        },
    )
    assert closed.status_code == 403
    assert HomeworkDraft.objects.get(user=user, assignment_key=assignment.key).answers == {}
    other = User.objects.create_user(email="another-steps@example.com")
    assert flow(other, assignment, Adapter()).status_code == 200
    assert HomeworkDraft.objects.get(user=other, assignment_key=assignment.key).answers == {}
    assert HomeworkDraft.objects.filter(assignment_key=assignment.key).count() == 2


def test_edit_prefill_and_legacy_invalidation(user, assignment):
    edited = Assignment(
        key=assignment.key,
        title=assignment.title,
        questions=assignment.questions,
        existing_answers={"q1": "b", "q2": "Previously submitted"},
    )
    assert flow(user, edited, Adapter(), query="?homework_step=q1").status_code == 200
    assert (
        HomeworkDraft.objects.get(user=user, assignment_key=edited.key).answers
        == edited.existing_answers
    )
    clear_draft(user, edited.key)
    assert not HomeworkDraft.objects.filter(user=user, assignment_key=edited.key).exists()


def test_persisted_submission_resumes_review_and_shows_submitted_state(user, assignment):
    submitted_assignment = Assignment(
        key=assignment.key,
        title=assignment.title,
        questions=assignment.questions,
        final_fields=assignment.final_fields,
        context={"homework_is_submitted": True},
    )

    response = flow(user, submitted_assignment, Adapter())

    assert response.status_code == 200
    parsed = StepperStateParser()
    parsed.feed(response.content.decode())
    assert parsed.current_step == "Review & submit"
    assert "Your homework was submitted." in parsed.status_messages


def test_semantic_step_label_is_used_in_navigation_question_and_review(user, assignment):
    labeled = Assignment(
        key=assignment.key,
        title=assignment.title,
        questions=(
            Question(
                "lip",
                "Share one progress link.",
                "long_text",
                step_label="Learning in Public",
            ),
        ),
    )

    question_page = flow(user, labeled, Adapter(), query="?homework_step=lip")
    assert b"<h2>Learning in Public</h2>" in question_page.content
    assert b">Learning in Public</a>" in question_page.content
    assert b">Question 1</a>" not in question_page.content

    review_page = flow(user, labeled, Adapter(), query="?homework_step=review")
    assert b">Learning in Public</a>" in review_page.content
    assert b"Question 1: Share one progress link." not in review_page.content


def test_draft_status_help_is_available_on_question_and_review_steps(user, assignment):
    for query in ("?homework_step=q1", "?homework_step=review"):
        response = flow(user, assignment, Adapter(), query=query)

        assert response.content.count(b'data-testid="homework-draft-status-help"') == 1
        assert b'<summary aria-label="About homework drafts">?</summary>' in response.content
        assert b"submitted only after you choose Submit homework" in response.content


def test_review_hides_stale_choice_keys_for_single_and_multiple_choice(user):
    adapter = Adapter()
    assignment = Assignment(
        key="course:cohort-1:stale-choice-homework",
        title="Homework with changed choices",
        questions=(
            Question("single", "Choose one", "choice", (Option("current", "Current option"),)),
            Question(
                "multiple",
                "Choose any",
                "checkbox",
                (Option("visible", "Visible option"),),
            ),
        ),
    )
    flow(user, assignment, adapter)
    draft = HomeworkDraft.objects.get(user=user, assignment_key=assignment.key)
    draft.answers = {
        "single": "option-retired-choice-42",
        "multiple": ["visible", "option-retired-checkbox-91"],
    }
    draft.save(update_fields=["answers"])

    response = flow(user, assignment, adapter, query="?homework_step=review")

    assert b"Previously selected option is no longer available." in response.content
    assert (
        b"Visible option, One or more previously selected options are no longer available."
        in response.content
    )
    assert b"option-retired-choice-42" not in response.content
    assert b"option-retired-checkbox-91" not in response.content


def test_accepted_submission_and_pending_draft_are_distinguished(user, assignment):
    submitted = Assignment(
        key=assignment.key,
        title=assignment.title,
        questions=assignment.questions,
        final_fields=assignment.final_fields,
        existing_answers={"q1": "a"},
        has_submission=True,
    )
    adapter = Adapter()

    accepted_page = flow(user, submitted, adapter, query="?homework_step=review")
    assert b"Your homework was submitted." in accepted_page.content
    assert b"Saved changes are a draft" not in accepted_page.content

    edited = flow(
        user,
        submitted,
        adapter,
        method="POST",
        data={
            "homework_step": "q1",
            "revision": "0",
            "answer": "b",
            "next_step": "q2",
        },
    )
    assert edited.status_code == 302
    pending_page = flow(user, submitted, adapter, query="?homework_step=review")
    assert b"Your submitted version is still accepted." in pending_page.content
    assert b"Saved changes are a draft until you submit them." in pending_page.content


def test_navigation_and_page_share_state_and_lookup_does_not_create_draft(user, assignment):
    initial = homework_state_for(user, assignment)
    assert initial.value == "not_submitted"
    assert HomeworkDraft.objects.count() == 0

    save_answer(user, assignment, question_key="q1", answer="b", revision=0)
    expected = homework_state_for(user, assignment)
    response = flow(user, assignment, Adapter(), query="?homework_step=q1")
    parsed = StepperStateParser()
    parsed.feed(response.content.decode())

    assert expected.value == "draft"
    assert parsed.homework_state == (expected.value, expected.aria_label)


def test_closed_review_keeps_accepted_snapshot_primary_and_hides_submit(user, assignment):
    accepted_time = datetime(2026, 9, 26, 10, 30, tzinfo=UTC)
    submitted = Assignment(
        key=assignment.key,
        title=assignment.title,
        questions=assignment.questions,
        final_fields=assignment.final_fields,
        availability="closed",
        accepted_submission=AcceptedSubmission(
            answers={"q1": "a", "q2": "accepted explanation"},
            final_fields={"link": "https://accepted.example"},
            submitted_at=accepted_time,
        ),
    )
    flow(user, submitted, Adapter())
    draft = save_answer(user, submitted, question_key="q1", answer="b", revision=0)
    save_final_fields(
        user,
        submitted,
        values={"link": "https://draft.example"},
        revision=draft.revision,
    )

    response = flow(user, submitted, Adapter(), query="?homework_step=review")
    content = response.content
    parsed = StepperStateParser()
    parsed.feed(content.decode())
    accepted_section = content.index(b'<h3 id="accepted-submission-title">Accepted submission')
    draft_section = content.index(b"Unsubmitted draft")

    assert parsed.homework_state == ("submitted", "Homework status: Submitted")
    assert b"2026" in content[accepted_section:draft_section]
    assert b"Alpha" in content[accepted_section:draft_section]
    assert b"https://accepted.example" in content[accepted_section:draft_section]
    assert b"Beta" not in content[accepted_section:draft_section]
    assert b"Beta" in content[draft_section:]
    assert b"https://draft.example" in content[draft_section:]
    assert b"Submit homework" not in content
    assert b'name="intent"' not in content


def test_scored_without_submission_shows_closed_status_and_no_submit_control(user, assignment):
    scored = Assignment(
        key=assignment.key,
        title=assignment.title,
        questions=assignment.questions,
        final_fields=assignment.final_fields,
        availability="scored",
    )
    response = flow(user, scored, Adapter(), query="?homework_step=review")

    assert b'data-homework-state="closed_not_submitted"' in response.content
    assert b"Closed \xe2\x80\x94 not submitted" in response.content
    assert b"Scored" not in response.content
    assert b"Submit homework" not in response.content


def test_closed_saved_draft_without_submission_is_not_shown_as_accepted(user, assignment):
    closed = Assignment(
        key=assignment.key,
        title=assignment.title,
        questions=assignment.questions,
        final_fields=assignment.final_fields,
        availability="closed",
    )
    flow(user, closed, Adapter())
    save_answer(user, closed, question_key="q2", answer="Saved but not submitted", revision=0)

    response = flow(user, closed, Adapter(), query="?homework_step=review")

    assert b'data-homework-state="closed_not_submitted"' in response.content
    assert b"Saved draft \xe2\x80\x94 not submitted" in response.content
    assert b"Saved but not submitted" in response.content
    assert b"Accepted submission" not in response.content
    assert b"Submit homework" not in response.content


def test_closed_availability_rejects_submit_even_when_adapter_allows_it(user, assignment):
    closed = Assignment(
        key=assignment.key,
        title=assignment.title,
        questions=assignment.questions,
        final_fields=assignment.final_fields,
        availability="closed",
    )
    adapter = Adapter()
    flow(user, closed, adapter)

    response = flow(
        user,
        closed,
        adapter,
        method="POST",
        data={
            "homework_step": "review",
            "revision": "0",
            "intent": "submit",
            "final_link": "",
        },
    )

    assert response.status_code == 403
    assert adapter.submissions == []
    assert HomeworkDraft.objects.filter(user=user, assignment_key=closed.key).exists()


def test_route_step_urls_are_canonical_and_legacy_query_links_still_work(user, assignment):
    adapter = Adapter()
    factory = RequestFactory()
    request = factory.get("/homework/intro")
    request.user = user
    response = handle_stepper(
        request,
        assignment,
        adapter,
        action="/homework/intro",
        step_param="homework_step",
        route_step="intro",
        step_url_builder=lambda step: f"/homework/{step}",
        query_params={"cohort": "cohort-1"},
    )
    assert response.status_code == 200
    assert b'href="/homework/q1?cohort=cohort-1"' in response.content

    request = factory.post(
        "/homework/q1",
        data={
            "assignment_key": assignment.key,
            "homework_step": "q1",
            "revision": "0",
            "answer": "b",
            "next_step": "q2",
            "draft_token": str(
                HomeworkDraft.objects.get(user=user, assignment_key=assignment.key).token
            ),
        },
    )
    request.user = user
    saved = handle_stepper(
        request,
        assignment,
        adapter,
        action="/homework/q1",
        step_param="homework_step",
        route_step="q1",
        step_url_builder=lambda step: f"/homework/{step}",
        query_params={"cohort": "cohort-1"},
    )
    assert saved.status_code == 302
    assert saved["Location"] == "/homework/q2?cohort=cohort-1"

    legacy = flow(user, assignment, adapter, query="?homework_step=q1")
    assert legacy.status_code == 200
    assert b"Question 1" in legacy.content


def test_invalid_choice_never_reaches_draft(user, assignment):
    with pytest.raises(ValidationError):
        save_answer(user, assignment, question_key="q1", answer="forged", revision=0)
    assert not HomeworkDraft.objects.filter(user=user).exists()


def test_clearing_choice_removes_only_that_answer(user, assignment):
    first = save_answer(user, assignment, question_key="q1", answer="a", revision=0)
    second = save_answer(
        user, assignment, question_key="q2", answer="Keep", revision=first.revision
    )
    cleared = save_answer(user, assignment, question_key="q1", answer="", revision=second.revision)
    assert cleared.answers == {"q2": "Keep"}


def test_navigation_identifiers_cannot_be_question_keys(user, assignment):
    invalid = Assignment(
        key=assignment.key,
        title=assignment.title,
        questions=(Question("review", "Impossible", "short_text"),),
    )
    with pytest.raises(ValueError, match="Question keys"):
        flow(user, invalid, Adapter())


def test_retry_of_successful_final_post_cannot_call_host_again(user, assignment):
    adapter = Adapter()
    flow(user, assignment, adapter)
    original_token = str(HomeworkDraft.objects.get(user=user, assignment_key=assignment.key).token)
    posted = {
        "homework_step": "review",
        "revision": "0",
        "intent": "submit",
        "draft_token": original_token,
        "final_link": "",
    }
    assert flow(user, assignment, adapter, method="POST", data=posted).status_code == 302
    assert len(adapter.submissions) == 1
    replay = flow(user, assignment, adapter, method="POST", data=posted)
    assert replay.status_code == 409
    assert len(adapter.submissions) == 1


def test_anonymous_and_read_denied_requests_do_not_create_a_draft(user, assignment):
    adapter = Adapter()
    assert flow(AnonymousUser(), assignment, adapter).status_code == 403
    adapter.policy = Eligibility(False, False, False, "Not enrolled")
    assert flow(user, assignment, adapter).status_code == 403
    assert HomeworkDraft.objects.count() == 0


def test_stale_question_link_redirects_with_notice(user, assignment):
    response = flow(user, assignment, Adapter(), query="?homework_step=old-question")
    assert response.status_code == 302
    assert response["Location"].endswith("homework_step=q1&notice=changed")


def test_query_string_cannot_forge_submission_success(user, assignment):
    response = flow(user, assignment, Adapter(), query="?homework_step=review&submitted=1")
    assert response.status_code == 200
    assert b"Your homework was submitted." not in response.content


def test_forged_assignment_and_question_posts_create_no_draft(user, assignment):
    adapter = Adapter()
    forged_assignment = handle_stepper(
        request(
            user,
            method="POST",
            data={
                "assignment_key": "forged",
                "homework_step": "q1",
                "revision": "0",
            },
        ),
        assignment,
        adapter,
        step_param="homework_step",
    )
    forged_question = handle_stepper(
        request(
            user,
            method="POST",
            data={
                "assignment_key": assignment.key,
                "homework_step": "forged",
                "revision": "0",
            },
        ),
        assignment,
        adapter,
        step_param="homework_step",
    )
    assert forged_assignment.status_code == 400
    assert forged_question.status_code == 400
    assert HomeworkDraft.objects.count() == 0
