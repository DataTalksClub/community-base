from django.db import transaction

from community_base.mail import send


def send_free_welcome(user):
    if user is None or not getattr(user, "pk", None):
        return None
    with transaction.atomic():
        return send(
            "accounts.free_welcome",
            user.email,
            {},
            f"accounts:free-welcome:{user.pk}",
            user=user,
        )
