from allauth.socialaccount.signals import pre_social_login, social_account_added
from django.dispatch import receiver


def _mark_social_identity(user, *, activate=False):
    if not getattr(user, "pk", None):
        return
    fields = []
    if not user.email_verified:
        user.email_verified = True
        fields.append("email_verified")
    if activate and user.signup_source == "unknown":
        user.signup_source = "oauth"
        fields.append("signup_source")
    if activate and not user.account_activated:
        user.account_activated = True
        fields.append("account_activated")
    if fields:
        user.save(update_fields=fields)


@receiver(pre_social_login, dispatch_uid="community_base.accounts.social_login")
def mark_social_login_verified(sender, request, sociallogin, **kwargs):
    _mark_social_identity(sociallogin.user)


@receiver(social_account_added, dispatch_uid="community_base.accounts.social_added")
def mark_social_account_added(sender, request, sociallogin, **kwargs):
    _mark_social_identity(sociallogin.user, activate=True)
    user = sociallogin.user
    if not getattr(user, "pk", None) or user.first_name or user.last_name:
        return
    data = getattr(sociallogin.account, "extra_data", {}) or {}
    first_name = str(data.get("given_name") or "").strip()
    last_name = str(data.get("family_name") or "").strip()
    if not first_name and not last_name:
        parts = str(data.get("name") or "").strip().split(maxsplit=1)
        first_name = parts[0] if parts else ""
        last_name = parts[1] if len(parts) == 2 else ""
    fields = []
    if first_name:
        user.first_name = first_name[:150]
        fields.append("first_name")
    if last_name:
        user.last_name = last_name[:150]
        fields.append("last_name")
    if fields:
        user.save(update_fields=fields)
