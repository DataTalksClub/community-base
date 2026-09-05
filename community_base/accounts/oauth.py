from allauth.socialaccount.models import SocialApp


def provider_context():
    configured = set(SocialApp.objects.exclude(client_id="").values_list("provider", flat=True))
    return {
        "oauth_google_enabled": "google" in configured,
        "oauth_github_enabled": "github" in configured,
        "oauth_slack_enabled": "slack" in configured,
    }
