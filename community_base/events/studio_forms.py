from django import forms

from community_base.events.models import Event, EventSeries, Host


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = (
            "title",
            "slug",
            "description",
            "kind",
            "platform",
            "start_datetime",
            "end_datetime",
            "timezone",
            "location",
            "required_level",
            "status",
            "event_series",
            "series_position",
            "hosts",
            "recording_url",
            "materials",
        )

    def clean_materials(self):
        return self.cleaned_data.get("materials") or []


class EventSeriesForm(forms.ModelForm):
    class Meta:
        model = EventSeries
        fields = (
            "name",
            "slug",
            "description",
            "cadence",
            "day_of_week",
            "start_time",
            "timezone",
            "required_level",
            "is_active",
        )


class HostForm(forms.ModelForm):
    class Meta:
        model = Host
        fields = (
            "name",
            "slug",
            "kind",
            "external_ref",
            "title",
            "bio",
            "photo_url",
            "email",
            "is_active",
        )


class GuestInvitationForm(forms.Form):
    email = forms.EmailField(max_length=254)


class RegistrationStateForm(forms.Form):
    state = forms.ChoiceField(
        choices=(("attended", "Attended"), ("no_show", "No show"), ("cancelled", "Cancelled"))
    )
