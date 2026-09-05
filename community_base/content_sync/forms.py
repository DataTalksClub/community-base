from django import forms

from community_base.content_sync.github import REPOSITORY_PATTERN
from community_base.content_sync.models import ContentSource


class ContentSourceForm(forms.ModelForm):
    webhook_secret = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to keep the existing secret.",
    )

    class Meta:
        model = ContentSource
        fields = ("repo_name", "is_private", "is_enabled", "max_files", "webhook_secret")

    def clean_repo_name(self):
        value = self.cleaned_data["repo_name"].strip()
        if not REPOSITORY_PATTERN.fullmatch(value):
            raise forms.ValidationError("Use the GitHub owner/repository format.")
        return value

    def clean_max_files(self):
        value = self.cleaned_data["max_files"]
        if not 1 <= value <= 100_000:
            raise forms.ValidationError("Maximum files must be between 1 and 100000.")
        return value

    def clean_webhook_secret(self):
        supplied = self.cleaned_data["webhook_secret"].strip()
        if supplied:
            return supplied
        if self.instance.pk and self.instance.webhook_secret:
            return self.instance.webhook_secret
        raise forms.ValidationError("A webhook secret is required.")
