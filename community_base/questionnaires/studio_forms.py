from django import forms
from django.db import transaction

from community_base.questionnaires.models import (
    CHOICE_TYPES,
    Persona,
    Question,
    Questionnaire,
    QuestionOption,
    ResponseQuestion,
    ResponseQuestionOption,
)


class QuestionnaireForm(forms.ModelForm):
    class Meta:
        model = Questionnaire
        fields = ("title", "slug", "purpose", "description", "is_active")


class PersonaForm(forms.ModelForm):
    class Meta:
        model = Persona
        fields = (
            "name",
            "archetype",
            "slug",
            "description",
            "default_questionnaire",
            "is_active",
            "order",
        )

    def clean_default_questionnaire(self):
        questionnaire = self.cleaned_data.get("default_questionnaire")
        if questionnaire is not None and questionnaire.purpose != "onboarding":
            raise forms.ValidationError("Choose an onboarding questionnaire.")
        return questionnaire


class QuestionFieldsMixin:
    options = forms.CharField(
        required=False,
        widget=forms.Textarea,
        help_text="One option per line. Add |free_text after a label to allow a description.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = self.instance
        if instance.pk:
            self.initial["options"] = "\n".join(
                f"{option.label}{'|free_text' if option.allows_free_text else ''}"
                for option in instance.options.all()
            )

    def clean(self):
        cleaned = super().clean()
        question_type = cleaned.get("question_type")
        raw_options = cleaned.get("options", "")
        options = []
        for line in raw_options.splitlines():
            label, separator, flag = line.partition("|")
            label = label.strip()
            if not label:
                continue
            if separator and flag.strip() not in {"", "free_text"}:
                self.add_error("options", f'Unknown option flag for "{label}".')
            options.append((label, flag.strip() == "free_text"))
        if question_type in CHOICE_TYPES and not options:
            self.add_error("options", "Choice questions need at least one option.")
        if question_type not in CHOICE_TYPES and options:
            self.add_error("options", "Only choice questions can have options.")
        minimum = cleaned.get("scale_min")
        maximum = cleaned.get("scale_max")
        if minimum is not None and maximum is not None and minimum > maximum:
            self.add_error("scale_max", "Maximum must be at least the minimum.")
        cleaned["parsed_options"] = options
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=commit)
        if commit:
            self.save_options(instance)
        return instance

    @transaction.atomic
    def save_options(self, instance):
        instance.options.all().delete()
        model = QuestionOption if isinstance(instance, Question) else ResponseQuestionOption
        parent_name = "question" if isinstance(instance, Question) else "response_question"
        model.objects.bulk_create(
            [
                model(
                    **{parent_name: instance},
                    label=label,
                    allows_free_text=allows_free_text,
                    order=order,
                )
                for order, (label, allows_free_text) in enumerate(
                    self.cleaned_data["parsed_options"]
                )
            ]
        )


class QuestionForm(QuestionFieldsMixin, forms.ModelForm):
    options = forms.CharField(
        required=False,
        widget=forms.Textarea,
        help_text="One option per line. Add |free_text after a label to allow a description.",
    )

    class Meta:
        model = Question
        fields = (
            "question_type",
            "prompt",
            "help_text",
            "is_required",
            "order",
            "scale_min",
            "scale_max",
        )


class ResponseQuestionForm(QuestionFieldsMixin, forms.ModelForm):
    options = forms.CharField(
        required=False,
        widget=forms.Textarea,
        help_text="One option per line. Add |free_text after a label to allow a description.",
    )

    class Meta:
        model = ResponseQuestion
        fields = (
            "question_type",
            "prompt",
            "help_text",
            "is_required",
            "order",
            "scale_min",
            "scale_max",
        )
