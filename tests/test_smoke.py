import tomllib
from pathlib import Path

import community_base


def test_version():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text())["project"]["version"]
    assert community_base.__version__ == expected
