from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

from community_base.accounts.models import EmailAlias


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """Connect verified provider identities to an active alias owner.

    Allauth handles direct primary-email matches. This hook covers a verified
    email retained as an alias after a merge, without importing site services.
    """

    def pre_social_login(self, request, sociallogin):
        if sociallogin.is_existing or getattr(sociallogin.user, "pk", None):
            return
        verified = {
            address.email.strip().lower()
            for address in sociallogin.email_addresses or ()
            if address.verified and address.email
        }
        if len(verified) != 1:
            return
        alias = (
            EmailAlias.objects.select_related("user")
            .filter(email__iexact=verified.pop(), user__is_active=True)
            .first()
        )
        if alias is not None:
            sociallogin.connect(request, alias.user)

    def is_open_for_signup(self, request, sociallogin):
        provider = getattr(getattr(sociallogin, "account", None), "provider", "")
        creates_user = not sociallogin.is_existing and not getattr(sociallogin.user, "pk", None)
        if provider == "slack" and creates_user:
            return False
        return super().is_open_for_signup(request, sociallogin)
