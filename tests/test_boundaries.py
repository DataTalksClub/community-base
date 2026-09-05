import ast
from pathlib import Path

FORBIDDEN_IMPORTS = {
    "analytics",
    "bookclub",
    "content",
    "courses",
    "crm",
    "integrations",
    "management_api",
    "management_auth",
    "payments",
    "plans",
    "studio_courses",
    "triggers",
    "website",
}
PACKAGE_ROOT = Path(__file__).parents[1] / "community_base"


def imported_modules(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_package_does_not_import_site_apps():
    violations = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        for module in imported_modules(path):
            if module.split(".", maxsplit=1)[0] in FORBIDDEN_IMPORTS:
                violations.append(f"{path.relative_to(PACKAGE_ROOT)}: {module}")

    assert not violations, "Site imports found:\n" + "\n".join(violations)
