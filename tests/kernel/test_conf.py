import subprocess
import sys

import pytest
from django.core.exceptions import ImproperlyConfigured

from community_base.kernel.conf import DEFAULTS, get


def test_settings_override_defaults(settings):
    settings.COMMUNITY_BASE = {"SITE_KEY": "example"}

    assert get("SITE_KEY") == "example"
    assert get("STUDIO_TITLE") == DEFAULTS["STUDIO_TITLE"]


def test_unknown_setting_is_rejected():
    with pytest.raises(ImproperlyConfigured, match="Unknown COMMUNITY_BASE setting"):
        get("NOT_DECLARED")


def test_missing_dictionary_uses_defaults(settings):
    del settings.COMMUNITY_BASE

    assert get("SITE_KEY") == DEFAULTS["SITE_KEY"]


def test_defaults_work_without_configured_django_settings():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from community_base.kernel.access import can_access; "
            "print(can_access(None, 0), can_access(None, 5))",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True False"
