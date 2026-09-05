from django import forms

from community_base.community.models import CallHost


class CallHostForm(forms.ModelForm):
    class Meta:
        model = CallHost
        fields = (
            "name",
            "slug",
            "role_label",
            "photo_url",
            "booking_url",
            "is_active",
            "capacity",
            "order",
        )
