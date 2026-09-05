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
