from community_base.questionnaires.models import (
    Answer,
    AnswerOptionText,
    ResponseQuestion,
    ResponseQuestionOption,
)

TEXT_TYPES = frozenset({"text", "long_text"})
NUMBER_TYPES = frozenset({"scale", "number"})
CHOICE_TYPES = frozenset({"single_choice", "multiple_choice"})


def build_response_questions(response):
    """Snapshot the base questions and options once for a response."""
    if response.response_questions.exists():
        return []
    created = []
    for base in response.questionnaire.questions.prefetch_related("options"):
        question = ResponseQuestion.objects.create(
            response=response,
            source_question=base,
            question_type=base.question_type,
            prompt=base.prompt,
            help_text=base.help_text,
            is_required=base.is_required,
            order=base.order,
            scale_min=base.scale_min,
            scale_max=base.scale_max,
        )
        ResponseQuestionOption.objects.bulk_create(
            [
                ResponseQuestionOption(
                    response_question=question,
                    source_option=option,
                    label=option.label,
                    allows_free_text=option.allows_free_text,
                    order=option.order,
                )
                for option in base.options.all()
            ]
        )
        created.append(question)
    return created


def field_name(question):
    return f"question_{question.pk}"


def option_text_field_name(question, option):
    return f"question_{question.pk}_option_{option.pk}_text"


class AnswerSaveError(Exception):
    def __init__(self, field_errors):
        self.field_errors = field_errors
        super().__init__("Answer validation failed")


def build_response_form_rows(response, *, post_data=None, field_errors=None):
    """Build renderer-neutral rows and preserve posted or stored values."""
    field_errors = field_errors or {}
    answers = {
        answer.question_id: answer
        for answer in response.answers.prefetch_related("selected_options", "option_texts")
    }
    rows = []
    for question in response.response_questions.prefetch_related("options"):
        name = field_name(question)
        answer = answers.get(question.pk)
        text_value = ""
        number_value = ""
        selected_ids = set()
        if post_data is not None:
            if question.question_type in TEXT_TYPES:
                text_value = post_data.get(name, "")
            elif question.question_type in NUMBER_TYPES:
                number_value = post_data.get(name, "")
            else:
                selected_ids = {int(value) for value in post_data.getlist(name) if value.isdigit()}
        elif answer is not None:
            text_value = answer.text_value or ""
            number_value = "" if answer.number_value is None else str(answer.number_value)
            selected_ids = {option.pk for option in answer.selected_options.all()}
        stored_option_text = (
            {item.selected_option_id: item.text_value for item in answer.option_texts.all()}
            if answer is not None and post_data is None
            else {}
        )
        options = []
        for option in question.options.all():
            text_name = option_text_field_name(question, option)
            options.append(
                {
                    "option": option,
                    "selected": option.pk in selected_ids,
                    "free_text_name": text_name,
                    "free_text_value": (
                        post_data.get(text_name, "")
                        if post_data is not None
                        else stored_option_text.get(option.pk, "")
                    ),
                }
            )
        rows.append(
            {
                "question": question,
                "field_name": name,
                "text_value": text_value,
                "number_value": number_value,
                "options": options,
                "error": field_errors.get(question.pk, ""),
            }
        )
    return rows


def _stage_answer(question, post_data, *, require_choice_free_text):
    name = field_name(question)
    if question.question_type in TEXT_TYPES:
        return "text", post_data.get(name, "").strip()
    if question.question_type in NUMBER_TYPES:
        raw = post_data.get(name, "").strip()
        if not raw:
            return "number", None
        try:
            value = int(raw)
        except (TypeError, ValueError) as error:
            raise ValueError("Enter a whole number.") from error
        if question.scale_min is not None and value < question.scale_min:
            raise ValueError(f"Enter a number of at least {question.scale_min}.")
        if question.scale_max is not None and value > question.scale_max:
            raise ValueError(f"Enter a number no greater than {question.scale_max}.")
        return "number", value

    options = list(question.options.all())
    valid_ids = {option.pk for option in options}
    values = post_data.getlist(name)
    if any(not value.isdigit() for value in values):
        raise ValueError("Pick a valid option.")
    selected_ids = {int(value) for value in values}
    if question.question_type == "single_choice" and len(selected_ids) > 1:
        raise ValueError("Pick only one option.")
    if selected_ids - valid_ids:
        raise ValueError("Pick a valid option.")
    option_texts = {}
    for option in options:
        if option.pk not in selected_ids or not option.allows_free_text:
            continue
        value = post_data.get(option_text_field_name(question, option), "").strip()
        if require_choice_free_text and not value:
            raise ValueError(f'Describe your "{option.label}" answer.')
        option_texts[option.pk] = value
    return "choice", selected_ids, option_texts


def save_response_answers(response, post_data, *, require_choice_free_text=False):
    """Validate every posted answer before updating any response data."""
    questions = list(response.response_questions.prefetch_related("options"))
    staged = []
    errors = {}
    for question in questions:
        try:
            staged.append(
                (
                    question,
                    _stage_answer(
                        question, post_data, require_choice_free_text=require_choice_free_text
                    ),
                )
            )
        except ValueError as error:
            errors[question.pk] = str(error)
    if errors:
        raise AnswerSaveError(errors)

    for question, item in staged:
        kind, value, *rest = item
        answer, _created = Answer.objects.get_or_create(response=response, question=question)
        answer.text_value = value if kind == "text" else ""
        answer.number_value = value if kind == "number" else None
        answer.save(update_fields=("text_value", "number_value", "updated_at"))
        if kind == "choice":
            answer.selected_options.set(value)
            option_texts = rest[0]
            AnswerOptionText.objects.filter(answer=answer).exclude(
                selected_option_id__in=value
            ).delete()
            for option_id, text in option_texts.items():
                if text:
                    AnswerOptionText.objects.update_or_create(
                        answer=answer,
                        selected_option_id=option_id,
                        defaults={"text_value": text},
                    )
                else:
                    AnswerOptionText.objects.filter(
                        answer=answer, selected_option_id=option_id
                    ).delete()
        else:
            answer.selected_options.clear()
            AnswerOptionText.objects.filter(answer=answer).delete()


def find_unanswered_required(response):
    answers = {
        answer.question_id: answer
        for answer in response.answers.prefetch_related("selected_options")
    }
    missing = []
    for question in response.response_questions.all():
        if not question.is_required:
            continue
        answer = answers.get(question.pk)
        if answer is None:
            missing.append(question)
        elif question.question_type in TEXT_TYPES and not answer.text_value.strip():
            missing.append(question)
        elif question.question_type in NUMBER_TYPES and answer.number_value is None:
            missing.append(question)
        elif question.question_type in CHOICE_TYPES and not answer.selected_options.exists():
            missing.append(question)
    return missing
