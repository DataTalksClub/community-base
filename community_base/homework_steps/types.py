"""Host adapter contract. All identifiers in these descriptors come from the server."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from django.http import HttpRequest

Answer = str | list[str]
QuestionType = Literal["choice", "checkbox", "short_text", "long_text"]
HomeworkAvailability = Literal["open", "closed", "scored"]


@dataclass(frozen=True)
class Option:
    key: str
    label: str


@dataclass(frozen=True)
class Question:
    key: str
    prompt: str
    type: QuestionType
    options: tuple[Option, ...] = ()
    step_label: str = ""


@dataclass(frozen=True)
class FinalField:
    key: str
    label: str
    type: Literal["text", "url", "textarea"] = "text"
    required: bool = False


@dataclass(frozen=True)
class QuestionResult:
    """The host's verdict on one accepted answer, supplied only once the host reveals it.

    ``correct_answer`` and ``explanation`` are display text; empty means the host has none to
    show. The package never derives any of this from a draft or an answer key.
    """

    correct: bool
    correct_answer: str = ""
    explanation: str = ""


@dataclass(frozen=True)
class AcceptedSubmission:
    """The learner's accepted snapshot, kept separate from an in-progress draft."""

    answers: dict[str, Answer] = field(default_factory=dict)
    final_fields: dict[str, str] = field(default_factory=dict)
    submitted_at: datetime | None = None


@dataclass(frozen=True)
class Assignment:
    key: str
    title: str
    questions: tuple[Question, ...]
    introduction: str = ""
    instructions: str = ""
    final_fields: tuple[FinalField, ...] = ()
    existing_answers: dict[str, Answer] = field(default_factory=dict)
    existing_final_fields: dict[str, str] = field(default_factory=dict)
    context: object = None
    has_submission: bool = False
    availability: HomeworkAvailability = "open"
    accepted_submission: AcceptedSubmission | None = None
    # Per-question results keyed by question key. ``None`` means the host reveals nothing yet:
    # a dated cohort's homework before scoring. A self-paced host supplies them on submit.
    question_results: dict[str, QuestionResult] | None = None


@dataclass(frozen=True)
class Eligibility:
    read: bool
    write: bool
    submit: bool
    reason: str = ""


class Adapter(Protocol):
    def eligibility(self, request: HttpRequest, assignment: Assignment) -> Eligibility: ...

    def submit(
        self,
        request: HttpRequest,
        assignment: Assignment,
        answers: dict[str, Answer],
        final_fields: dict[str, str],
    ) -> object: ...
