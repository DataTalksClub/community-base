from allauth.account.models import EmailAddress
from django import forms
from django.contrib.auth import get_user_model
from django.db import transaction

from community_base.accounts.models import IMPORT_BATCH_SOURCE_CHOICES, EmailAlias
from community_base.accounts.services.email_resolution import normalize_email
from community_base.accounts.services.free_welcome import send_free_welcome


class StaffUserCreateForm(forms.Form):
    email = forms.EmailField(max_length=254)
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    email_verified = forms.BooleanField(required=False)
    send_welcome = forms.BooleanField(required=False)

    def clean_email(self):
        email = normalize_email(self.cleaned_data["email"])
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account already uses this email address.")
        if EmailAlias.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account alias already uses this email address.")
        return email

    def save(self):
        with transaction.atomic():
            user = get_user_model().objects.create_user(
                email=self.cleaned_data["email"],
                first_name=self.cleaned_data["first_name"].strip(),
                last_name=self.cleaned_data["last_name"].strip(),
                email_verified=self.cleaned_data["email_verified"],
                account_activated=True,
                signup_source="staff_create",
            )
            EmailAddress.objects.create(
                user=user,
                email=user.email,
                verified=user.email_verified,
                primary=True,
            )
            if self.cleaned_data["send_welcome"]:
                send_free_welcome(user)
        return user


class StaffImportForm(forms.Form):
    source = forms.ChoiceField(choices=IMPORT_BATCH_SOURCE_CHOICES)
    csv_file = forms.FileField()
    dry_run = forms.BooleanField(required=False, initial=True)
    send_welcome = forms.BooleanField(required=False)
    default_tags = forms.CharField(max_length=500, required=False)

    def clean_csv_file(self):
        upload = self.cleaned_data["csv_file"]
        if upload.size > 5_000_000:
            raise forms.ValidationError("CSV files must be 5 MB or smaller.")
        try:
            content = upload.read().decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise forms.ValidationError("CSV files must use UTF-8 encoding.") from error
        upload.seek(0)
        return content

    def parsed_tags(self):
        return tuple(
            part.strip() for part in self.cleaned_data["default_tags"].split(",") if part.strip()
        )


class StaffMergeForm(forms.Form):
    canonical_user_id = forms.IntegerField(min_value=1)
    secondary_user_id = forms.IntegerField(min_value=1)
    dry_run = forms.BooleanField(required=False, initial=True)
    confirm = forms.BooleanField(required=True)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("canonical_user_id") == cleaned.get("secondary_user_id"):
            self.add_error("secondary_user_id", "Choose two different accounts.")
        return cleaned
