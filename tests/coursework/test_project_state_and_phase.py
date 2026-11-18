"""Tests for project_state, project_phase, peer_pseudonym, and state commands."""

from datetime import timedelta
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from community_base.coursework.models import Project, ProjectState
from community_base.coursework.peer_pseudonym import peer_pseudonym
from community_base.coursework.project_phase import (
    FEEDBACK,
    MISSED,
    REVIEW,
    SUBMIT,
    WAITING,
    attempt_phase,
)
from community_base.coursework.project_state import (
    ProjectStateError,
    parse_state,
    set_project_state,
)
from community_base.curriculum.models import Cohort, Course


def test_peer_pseudonym_is_deterministic():
    a = peer_pseudonym(1, 10)
    b = peer_pseudonym(1, 10)
    c = peer_pseudonym(2, 10)
    assert a == b
    assert " " in a
    assert a != c


def test_parse_state_accepts_code_name_and_label():
    assert parse_state("PR") == ProjectState.PEER_REVIEWING
    assert parse_state("peer_reviewing") == ProjectState.PEER_REVIEWING
    assert parse_state("Peer reviewing") == ProjectState.PEER_REVIEWING
    with pytest.raises(ProjectStateError, match="Unknown state"):
        parse_state("bogus")


@pytest.mark.django_db
def test_set_project_state_and_management_commands():
    now = timezone.now()
    course = Course.objects.create(slug="ml", title="ML")
    cohort = Cohort.objects.create(
        course=course,
        slug="c1",
        title="Cohort 1",
        mode="cohort",
        start_date=now.date(),
        end_date=(now + timedelta(days=30)).date(),
    )
    project = Project.objects.create(
        cohort=cohort,
        slug="p1",
        title="P1",
        submission_due_date=now + timedelta(days=7),
        peer_review_due_date=now + timedelta(days=14),
    )

    with pytest.raises(ProjectStateError, match="Peer reviewing"):
        set_project_state(project, ProjectState.COMPLETED)

    out = StringIO()
    call_command("set_project_state", "ml", "p1", "peer_reviewing", stdout=out)
    project.refresh_from_db()
    assert project.state == ProjectState.PEER_REVIEWING.value

    call_command("close_peer_review", "ml", "p1", stdout=out)
    project.refresh_from_db()
    assert project.state == ProjectState.COMPLETED.value

    with pytest.raises(CommandError, match="not found"):
        call_command("set_project_state", "missing", "p1", "PR")


@pytest.mark.django_db
def test_set_project_state_rejects_self_paced():
    course = Course.objects.create(slug="sp", title="SP")
    cohort = Cohort.objects.create(course=course, slug="self-paced", title="SP", mode="self_paced")
    project = Project.objects.create(cohort=cohort, slug="p1", title="P1")
    with pytest.raises(ProjectStateError, match="Self-paced"):
        set_project_state(project, ProjectState.PEER_REVIEWING)


def test_attempt_phase_dated_states():
    now = timezone.now()
    proj = SimpleNamespace(
        uses_pooled_review=False,
        state=ProjectState.COLLECTING_SUBMISSIONS.value,
        submission_due_date=now + timedelta(days=2),
        peer_review_due_date=now + timedelta(days=9),
    )
    assert attempt_phase(proj, None, [], now).key == SUBMIT

    proj.state = ProjectState.PEER_REVIEWING.value
    assert attempt_phase(proj, None, [], now).key == MISSED
    sub = SimpleNamespace(review_state="IR")
    assert attempt_phase(proj, sub, [], now).key == WAITING
    reviews = [SimpleNamespace(state="TR"), SimpleNamespace(state="SU")]
    phase = attempt_phase(proj, sub, reviews, now)
    assert phase.key == REVIEW
    assert phase.reviews_done == 1
    assert phase.reviews_pending == 1
    assert phase.certificate_blocked is True

    proj.state = ProjectState.COMPLETED.value
    assert attempt_phase(proj, sub, reviews, now).key == FEEDBACK
