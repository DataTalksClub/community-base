from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction

from community_base.accounts.models import EmailAlias
from community_base.accounts.services.email_resolution import normalize_email


class AliasError(ValueError):
    pass


def add_email_alias(user, email, *, source=EmailAlias.Source.MANUAL, actor=None, note=""):
    normalized = normalize_email(email)
    try:
        validate_email(normalized)
    except ValidationError as error:
        raise AliasError("Enter a valid email address.") from error
    if normalized == normalize_email(user.email):
        raise AliasError("A primary login email cannot also be an alias.")
    if get_user_model().objects.filter(email__iexact=normalized).exists():
        raise AliasError("That email is already a primary login.")
    with transaction.atomic():
        existing = EmailAlias.objects.select_for_update().filter(email__iexact=normalized).first()
        if existing is not None:
            if existing.user_id != user.pk:
                raise AliasError("That email is already an alias of another account.")
            return existing, False
        try:
            alias = EmailAlias.objects.create(
                user=user,
                email=normalized,
                source=source,
                created_by=actor,
                note=note.strip(),
            )
        except IntegrityError as error:
            raise AliasError("That email cannot be added as an alias.") from error
    return alias, True


def remove_email_alias(user, email):
    deleted, _detail = EmailAlias.objects.filter(
        user=user,
        email__iexact=normalize_email(email),
    ).delete()
    return bool(deleted)
