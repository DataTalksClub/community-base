import pytest
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string

from community_base.questionnaires.models import (
    Answer,
    AnswerOptionText,
    Question,
    Questionnaire,
    QuestionOption,
    Response,
)
from community_base.questionnaires.services import (
    AnswerSaveError,
    build_response_form_rows,
    build_response_questions,
    find_unanswered_required,
    save_response_answers,
)

pytestmark = pytest.mark.django_db


class PostData(dict):
    def getlist(self, key):
        value = self.get(key)
        if value is None:
            return []
        return value if isinstance(value, list) else [value]


@pytest.fixture
def response():
    user = get_user_model().objects.create_user(email="member@example.com")
    questionnaire = Questionnaire.objects.create(title="Feedback", purpose="feedback")
    text = Question.objects.create(
        questionnaire=questionnaire,
        question_type="long_text",
        prompt="How did it go?",
        is_required=True,
        order=0,
    )
    scale = Question.objects.create(
        questionnaire=questionnaire,
        question_type="scale",
        prompt="Rate it",
        scale_min=1,
        scale_max=5,
        order=1,
    )
    choice = Question.objects.create(
        questionnaire=questionnaire,
        question_type="single_choice",
        prompt="Join next?",
        order=2,
    )
    QuestionOption.objects.create(question=choice, label="Yes", order=0)
    QuestionOption.objects.create(question=choice, label="Other", allows_free_text=True, order=1)
    result = Response.objects.create(questionnaire=questionnaire, respondent=user)
    build_response_questions(result)
    result.test_questions = {
        item.source_question_id: item for item in result.response_questions.all()
    }
    result.test_sources = {"text": text, "scale": scale, "choice": choice}
    return result


def question_for(response, kind):
    return response.test_questions[response.test_sources[kind].pk]


def test_snapshots_questions_options_and_is_idempotent(response):
    choice = question_for(response, "choice")

    assert response.response_questions.count() == 3
    assert list(choice.options.values_list("label", flat=True)) == ["Yes", "Other"]
    assert build_response_questions(response) == []


def test_snapshot_is_unchanged_after_base_edit(response):
    source = response.test_sources["text"]
    snapshot = question_for(response, "text")
    source.prompt = "Changed later"
    source.save()

    snapshot.refresh_from_db()
    assert snapshot.prompt == "How did it go?"


def test_saves_all_answer_types_and_free_text(response):
    text = question_for(response, "text")
    scale = question_for(response, "scale")
    choice = question_for(response, "choice")
    other = choice.options.get(label="Other")

    save_response_answers(
        response,
        PostData(
            {
                f"question_{text.pk}": "Great sprint",
                f"question_{scale.pk}": "4",
                f"question_{choice.pk}": str(other.pk),
                f"question_{choice.pk}_option_{other.pk}_text": "With pairing",
            }
        ),
    )

    assert Answer.objects.get(question=text).text_value == "Great sprint"
    assert Answer.objects.get(question=scale).number_value == 4
    answer = Answer.objects.get(question=choice)
    assert answer.display_value == "Other: With pairing"
    assert AnswerOptionText.objects.get(answer=answer).text_value == "With pairing"


@pytest.mark.parametrize("value", ["zero", "0", "6"])
def test_invalid_number_aborts_every_write(response, value):
    text = question_for(response, "text")
    scale = question_for(response, "scale")

    with pytest.raises(AnswerSaveError):
        save_response_answers(
            response,
            PostData({f"question_{text.pk}": "valid", f"question_{scale.pk}": value}),
        )

    assert response.answers.count() == 0


def test_unknown_choice_aborts_every_write(response):
    choice = question_for(response, "choice")

    with pytest.raises(AnswerSaveError, match="Answer validation failed"):
        save_response_answers(response, PostData({f"question_{choice.pk}": "999999"}))

    assert response.answers.count() == 0


def test_submit_can_require_selected_option_description(response):
    choice = question_for(response, "choice")
    other = choice.options.get(label="Other")

    with pytest.raises(AnswerSaveError) as error:
        save_response_answers(
            response,
            PostData({f"question_{choice.pk}": str(other.pk)}),
            require_choice_free_text=True,
        )

    assert error.value.field_errors[choice.pk] == 'Describe your "Other" answer.'


def test_form_rows_resume_values_and_renderer(response):
    text = question_for(response, "text")
    save_response_answers(response, PostData({f"question_{text.pk}": "Saved draft"}))

    rows = build_response_form_rows(response)
    html = render_to_string("questionnaires/_response_form.html", {"response_form_rows": rows})

    assert rows[0]["text_value"] == "Saved draft"
    assert "Saved draft" in html
    assert 'name="question_' in html
    assert 'type="number"' in html
    assert 'type="radio"' in html


def test_posted_values_win_when_rebuilding_error_rows(response):
    text = question_for(response, "text")
    rows = build_response_form_rows(
        response,
        post_data=PostData({f"question_{text.pk}": "Unsaved value"}),
        field_errors={text.pk: "Fix this answer."},
    )

    assert rows[0]["text_value"] == "Unsaved value"
    assert rows[0]["error"] == "Fix this answer."


def test_required_answers_are_derived_by_type(response):
    text = question_for(response, "text")
    assert find_unanswered_required(response) == [text]

    save_response_answers(response, PostData({f"question_{text.pk}": "done"}))

    assert find_unanswered_required(response) == []
