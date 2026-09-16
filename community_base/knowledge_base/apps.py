from django.apps import AppConfig


class KnowledgeBaseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.knowledge_base"
    label = "cb_knowledge_base"
    verbose_name = "Knowledge base"

    def ready(self):
        from community_base.knowledge_base.studio_registration import register_studio

        register_studio()
