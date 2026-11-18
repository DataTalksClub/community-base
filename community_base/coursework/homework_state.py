"""Homework state changes: close a homework or set it to any state.

Donor parity with the course management platform (CMP), where staff change a
homework's state through the homework ``PATCH`` endpoint (``state`` one of
``CL``, ``OP``, ``SC``) and through Django admin. CMP applies the new value as
is: there is no transition table and no side effect, so the package does the
same. Scoring stays with ``scoring.score_homework_submissions``, which already
refuses a ``CLOSED`` homework and marks a homework ``SCORED`` on success.

Both sites call this one service: the bearer API in ``staff_api_views``, the
Studio action in ``studio_views``, or their own views and commands.
"""

from dataclasses import dataclass

from django.db import transaction

from community_base.coursework.models import Homework, HomeworkState

VALID_HOMEWORK_STATES = tuple(sorted(state.value for state in HomeworkState))


class InvalidHomeworkState(ValueError):
    """Raised for a state that is neither a ``HomeworkState`` code nor a name."""

    def __init__(self, value):
        self.value = value
        super().__init__(f"Invalid state {value!r}. Must be one of: {list(VALID_HOMEWORK_STATES)}")


@dataclass(frozen=True)
class HomeworkStateChange:
    """Outcome of one state change; ``changed`` is false for a no-op."""

    homework: Homework
    previous_state: str
    state: str

    @property
    def changed(self) -> bool:
        return self.previous_state != self.state


def parse_homework_state(value) -> HomeworkState:
    """Resolve ``value`` to a ``HomeworkState``.

    Accepts the enum itself, the stored code CMP's API uses (``"CL"``), or the
    lower-case name the sites' shared ``open|closed|scored`` vocabulary uses
    (``"closed"``). Matching is case-insensitive; anything else raises
    ``InvalidHomeworkState``.
    """

    if isinstance(value, HomeworkState):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        for state in HomeworkState:
            if normalized.upper() in (state.value, state.name):
                return state
    raise InvalidHomeworkState(value)


@transaction.atomic
def set_homework_state(homework: Homework, state) -> HomeworkStateChange:
    """Set ``homework.state`` to ``state`` and save only that column.

    The row is re-read under a lock so a concurrent scoring run or a second
    state change cannot be overwritten with a stale value. The passed instance
    is updated in place so callers can keep using it.
    """

    target = parse_homework_state(state)
    locked = Homework.objects.select_for_update().get(pk=homework.pk)
    previous = locked.state
    if previous != target.value:
        locked.state = target.value
        locked.save(update_fields=["state"])
    homework.state = target.value
    return HomeworkStateChange(homework=homework, previous_state=previous, state=target.value)


def close_homework(homework: Homework) -> HomeworkStateChange:
    """Close a homework to new submissions (``HomeworkState.CLOSED``)."""

    return set_homework_state(homework, HomeworkState.CLOSED)
