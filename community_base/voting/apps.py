from django.apps import AppConfig


class VotingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.voting"
    label = "voting"
    verbose_name = "Voting"
