from django import forms

from community_base.onboarding.models import FlowAssignment, OnboardingFlow, OnboardingStep


class OnboardingFlowForm(forms.ModelForm):
    class Meta:
        model = OnboardingFlow
        fields = ("slug", "title", "is_default", "active")


class OnboardingStepForm(forms.ModelForm):
    class Meta:
        model = OnboardingStep
        fields = ("order", "kind", "config", "required")


class FlowAssignmentForm(forms.ModelForm):
    class Meta:
        model = FlowAssignment
        fields = ("group", "min_level", "priority")
