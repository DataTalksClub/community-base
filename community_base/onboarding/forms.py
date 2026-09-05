from django import forms

from community_base.accounts.models import MemberProfile
from community_base.accounts.services.profile import PROFILE_FIELDS, update_profile


class ProfileStepForm(forms.ModelForm):
    class Meta:
        model = MemberProfile
        fields = PROFILE_FIELDS

    def save_for(self, user):
        values = {name: self.cleaned_data.get(name) or "" for name in PROFILE_FIELDS}
        revision = self.instance.revision if self.instance.pk else 0
        return update_profile(user, values, expected_revision=revision)
