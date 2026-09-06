from django import forms

from community_base.events.models import Event, EventSeries, Host


class EventForm(forms.ModelForm):
    STATUS_TRANSITIONS = {
        "draft": {"draft", "upcoming", "cancelled"},
        "upcoming": {"upcoming", "completed", "cancelled"},
        "completed": {"completed", "archived"},
        "cancelled": {"cancelled", "archived"},
        "archived": {"archived"},
    }

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

    def clean_status(self):
        status = self.cleaned_data["status"]
        if self.instance.pk:
            original = Event.objects.only("status").get(pk=self.instance.pk).status
            if status not in self.STATUS_TRANSITIONS[original]:
                raise forms.ValidationError(f"An event cannot move from {original} to {status}.")
        return status


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
