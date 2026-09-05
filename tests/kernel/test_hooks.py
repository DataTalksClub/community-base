from community_base.kernel.hooks import Hook, resolve


class ExampleHooks:
    access_policy = Hook("ACCESS_POLICY", "community_base.kernel.access.RegisteredOnlyPolicy")


def test_resolve_is_cached():
    resolve.cache_clear()

    first = resolve("community_base.kernel.access.OpenPolicy")
    second = resolve("community_base.kernel.access.OpenPolicy")

    assert first is second
    assert resolve.cache_info().hits == 1


def test_hook_uses_default_when_setting_is_none(settings):
    settings.COMMUNITY_BASE = {"ACCESS_POLICY": None}

    assert ExampleHooks().access_policy.__name__ == "RegisteredOnlyPolicy"
