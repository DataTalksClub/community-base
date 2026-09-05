def allauth_settings():
    """Return the portable django-allauth settings used by package accounts."""

    return {
        "ACCOUNT_EMAIL_VERIFICATION": "none",
        "ACCOUNT_LOGIN_METHODS": {"email"},
        "ACCOUNT_SIGNUP_FIELDS": ["email*"],
        "ACCOUNT_SIGNUP_REDIRECT_URL": "/",
        "ACCOUNT_UNIQUE_EMAIL": True,
        "ACCOUNT_USER_MODEL_EMAIL_FIELD": "email",
        "ACCOUNT_USER_MODEL_USERNAME_FIELD": None,
        "SOCIALACCOUNT_ADAPTER": "community_base.accounts.adapters.SocialAccountAdapter",
        "SOCIALACCOUNT_AUTO_SIGNUP": True,
        "SOCIALACCOUNT_EMAIL_AUTHENTICATION": True,
        "SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT": True,
        "SOCIALACCOUNT_LOGIN_ON_GET": True,
        "SOCIALACCOUNT_PROVIDERS": {
            "google": {
                "SCOPE": ["profile", "email"],
                "AUTH_PARAMS": {"access_type": "online"},
            },
            "github": {"SCOPE": ["user:email"]},
            "slack": {"SCOPE": ["openid", "profile", "email"]},
        },
    }
