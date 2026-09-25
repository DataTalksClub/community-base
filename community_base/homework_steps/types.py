"""Host adapter contract. All identifiers in these descriptors come from the server."""

from dataclasses import dataclass, field
from typing import Literal, Protocol

from django.http import HttpRequest

Answer = str | list[str]
QuestionType = Literal["choice", "checkbox", "short_text", "long_text"]


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
