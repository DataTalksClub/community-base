"""The knowledge base app must boot without the curriculum app.

AISL (A7.1) installs `community_base.knowledge_base` while keeping its own
events and curriculum apps; the knowledge base models may only depend on
app-neutral modules (`content_sync.provenance`, model-free rendering).
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

BOOT_WITHOUT_CURRICULUM = """
import django
from django.conf import settings

settings.configure(
    INSTALLED_APPS=[
        "django.contrib.contenttypes",
        "django.contrib.auth",
        "community_base.knowledge_base",
    ],
    DATABASES={
        "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"},
    },
    DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
)
django.setup()

from community_base.knowledge_base.models import KnowledgeBasePage

assert KnowledgeBasePage._meta.app_config.name == "community_base.knowledge_base"
print("booted")
"""


def test_kb_models_load_without_the_curriculum_app():
    result = subprocess.run(
        [sys.executable, "-c", BOOT_WITHOUT_CURRICULUM],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "booted" in result.stdout
