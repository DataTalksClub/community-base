from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError


class LoginForm(forms.Form):
    email = forms.EmailField(
        max_length=254, widget=forms.EmailInput(attrs={"autocomplete": "email"})
    )
    password = forms.CharField(
        max_length=4096,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )


class RegistrationForm(forms.Form):
    next = forms.CharField(required=False, widget=forms.HiddenInput)
    email = forms.EmailField(
        max_length=254, widget=forms.EmailInput(attrs={"autocomplete": "email"})
    )
    password = forms.CharField(
        max_length=4096,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        if password:
            try:
                validate_password(password, get_user_model()(email=cleaned.get("email", "")))
            except ValidationError as error:
                self.add_error("password", error)
        return cleaned


class PasswordResetRequestForm(forms.Form):
    email = forms.EmailField(
        max_length=254, widget=forms.EmailInput(attrs={"autocomplete": "email"})
    )


class PasswordResetForm(forms.Form):
    new_password = forms.CharField(
        max_length=4096,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_new_password(self):
        password = self.cleaned_data["new_password"]
        try:
            validate_password(password, self.user)
        except ValidationError as error:
            raise forms.ValidationError(error.messages) from error
        return password
