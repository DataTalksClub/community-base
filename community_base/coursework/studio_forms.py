"""Forms for the coursework Studio surfaces.

``HomeworkSubmissionEditForm`` mirrors the donor form in
``studio_courses/forms.py``: one free-text field per question, the
learning-in-public links as a textarea, the FAQ url and an optional FAQ-score
override that falls back to the stored score when left empty.
"""

from django import forms

from community_base.coursework.models import Homework, Submission


class HomeworkSubmissionEditForm(forms.Form):
    learning_in_public_links = forms.CharField(required=False)
    faq_contribution_url = forms.CharField(required=False)
    faq_score = forms.IntegerField(required=False, min_value=0)

    def __init__(self, *args, submission: Submission, homework: Homework, **kwargs):
        super().__init__(*args, **kwargs)
        self.submission = submission
        self.homework = homework
        self.questions = list(homework.questions.order_by("id"))
        for question in self.questions:
            self.fields[f"answer_{question.id}"] = forms.CharField(required=False)

    def clean_faq_score(self):
        score = self.cleaned_data["faq_score"]
        if score is None:
            return self.submission.faq_score
        return score

    def clean(self):
        cleaned_data = super().clean()
        cleaned_data["answers_by_question"] = [
            (question, cleaned_data.get(f"answer_{question.id}", "")) for question in self.questions
        ]
        raw_links = cleaned_data.get("learning_in_public_links", "").splitlines()
        links = [raw_link.strip() for raw_link in raw_links if raw_link.strip()]
        cleaned_data["learning_in_public_links_list"] = links or None
        return cleaned_data


def first_form_error(form) -> str:
    for errors in form.errors.values():
        if errors:
            return str(errors[0])
    return "Invalid form data"
