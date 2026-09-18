from django.apps import AppConfig


class KernelConfig(AppConfig):
    name = "community_base.kernel"
    label = "cb_kernel"
    verbose_name = "Community Base Kernel"

    def ready(self) -> None:
        from community_base.kernel import checks  # noqa: F401
