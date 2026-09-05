import pytest

from community_base.studio import builtin, providers, registry, user_registry
from testproject.studio_tags import clear as clear_test_tags


def register_package_studio():
    from community_base.api.studio_registration import register_studio as register_api
    from community_base.config.studio_registration import register_studio as register_config
    from community_base.jobs.studio_registration import register_studio as register_jobs
    from community_base.mail.studio_registration import register_studio as register_mail

    builtin.register_builtin_section()
    register_config()
    register_api()
    register_jobs()
    register_mail()


@pytest.fixture(autouse=True)
def isolated_studio_registries():
    registry._clear()
    providers._clear()
    user_registry._clear()
    clear_test_tags()
    register_package_studio()
    yield
    registry._clear()
    providers._clear()
    user_registry._clear()
    clear_test_tags()
    register_package_studio()
