import pytest

from community_base.studio import builtin, providers, registry


@pytest.fixture(autouse=True)
def isolated_studio_registries():
    registry._clear()
    providers._clear()
    builtin.register_builtin_section()
    yield
    registry._clear()
    providers._clear()
    builtin.register_builtin_section()
