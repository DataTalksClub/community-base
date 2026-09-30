"""Independent invalid mixed modules are all protected in a partial run."""

import re
import shutil
import uuid

from community_base.content_sync.convert.courses import convert_course_repository
from tests.curriculum.test_mixed_source import mixed_homework_course


def _second_module(root):
    first = root / "01-week-one"
    second = root / "03-extra-week"
    shutil.copytree(first, second)
    for path in second.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text()
        text = re.sub(
            r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}",
            lambda match: str(uuid.uuid5(uuid.NAMESPACE_URL, match.group())),
            text,
        )
        path.write_text(text)
    return first, second


def _file_bytes(root):
    found = {}
    for path in root.rglob("*"):
        if path.is_file():
            found[path.relative_to(root)] = path.read_bytes()
    return found


def test_every_invalid_mixed_module_stays_unchanged_while_course_converts(tmp_path):
    root = mixed_homework_course(tmp_path)
    modules = _second_module(root)
    course = root / "course.yaml"
    course.write_text("schema_version: 2\n" + course.read_text())
    before = {}
    for module in modules:
        (module / "02-direct.md").rename(module / "direct.md")
        manifest = module / "module.yaml"
        manifest.write_text("schema_version: 2\n" + manifest.read_text())
        before[module.name] = _file_bytes(module)

    report = convert_course_repository(root)

    refused = set()
    for item in report.refusals:
        if item.path.endswith("direct.md"):
            refused.add(item.path)
    assert refused == {f"{module.name}/direct.md" for module in modules}
    assert all(_file_bytes(module) == before[module.name] for module in modules)
    for change in report.changes:
        assert not any(
            change.path.startswith(f"{module.name}/")
            and change.action in ("rewritten", "created", "renamed")
            for module in modules
        )
    assert "schema_version" not in course.read_text()
    assert report.verify() == []
