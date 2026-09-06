from django import forms


class AnonymousEventRegistrationForm(forms.Form):
    email = forms.EmailField(
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )
    display_name = forms.CharField(max_length=200, required=False)
    privacy_acknowledged = forms.BooleanField()
    newsletter_consent = forms.BooleanField(required=False)


class EventFeedbackForm(forms.Form):
    rating = forms.TypedChoiceField(
        choices=(("", "No rating"), *((value, str(value)) for value in range(1, 6))),
        coerce=lambda value: int(value) if value else None,
        required=False,
    )
    comment = forms.CharField(max_length=5000, required=False, widget=forms.Textarea)
    would_change = forms.CharField(max_length=5000, required=False, widget=forms.Textarea)

    def clean(self):
        cleaned = super().clean()
        if not any((cleaned.get("rating"), cleaned.get("comment"), cleaned.get("would_change"))):
            raise forms.ValidationError("Add a rating or comment before submitting feedback.")
        return cleaned
