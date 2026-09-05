import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from community_base.questionnaires.models import Questionnaire, Response
from community_base.questionnaires.response_workflows import (
    ResponseNotSubmitted,
    compact_response_queryset,
    transition_response_review,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def users():
    model = get_user_model()
    return (
        model.objects.create_user(email="member@example.com"),
        model.objects.create_user(email="operator@example.com", is_staff=True),
    )


def make_response(user, *, purpose="general", submitted=True):
    questionnaire = Questionnaire.objects.create(title=f"{purpose} intake", purpose=purpose)
    response = Response.objects.create(questionnaire=questionnaire, respondent=user)
    if submitted:
        response.mark_submitted()
    return response


def test_queue_filters_search_purpose_and_review_state(users):
    member, _operator = users
    awaiting = make_response(member, purpose="feedback")
    make_response(member, purpose="general")

    rows = compact_response_queryset(purpose="feedback", search="MEMBER", review="awaiting")

    assert list(rows) == [awaiting]
    assert rows[0].answered_count == 0


def test_review_and_reopen_are_audited_without_pii(users, settings):
    member, operator = users
    response = make_response(member)
    events = []
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "STUDIO_AUDIT_WRITER": lambda **event: events.append(event),
    }

    reviewed, changed = transition_response_review(
        response_id=response.pk, reviewed=True, actor=operator
    )
    reopened, reopened_changed = transition_response_review(
        response_id=response.pk, reviewed=False, actor=operator
    )

    assert changed is reopened_changed is True
    assert reviewed.review_state == "reviewed"
    assert reopened.review_state == "awaiting"
    assert [event["event"] for event in events] == [
        "questionnaires.response.reviewed",
        "questionnaires.response.reopened",
    ]
    assert "member@example.com" not in str(events)


def test_review_noop_writes_no_duplicate_audit(users, settings):
    member, operator = users
    response = make_response(member)
    response.reviewed_at = timezone.now()
    response.reviewed_by = operator
    response.save()
    events = []
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "STUDIO_AUDIT_WRITER": lambda **event: events.append(event),
    }

    _response, changed = transition_response_review(
        response_id=response.pk, reviewed=True, actor=operator
    )

    assert changed is False
    assert events == []


def test_draft_cannot_be_reviewed(users):
    member, operator = users
    response = make_response(member, submitted=False)

    with pytest.raises(ResponseNotSubmitted):
        transition_response_review(response_id=response.pk, reviewed=True, actor=operator)
