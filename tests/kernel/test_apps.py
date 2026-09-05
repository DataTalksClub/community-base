from django.apps import apps


def test_kernel_app_uses_package_label():
    config = apps.get_app_config("cb_kernel")

    assert config.name == "community_base.kernel"
    assert not list(config.get_models())
