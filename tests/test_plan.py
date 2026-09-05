from pathlib import Path

import scripts.plan as plan


def configure_plan(monkeypatch, tmp_path: Path, phase_text: str, status=None):
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    (plan_dir / "phase-0.md").write_text(phase_text)
    status_path = plan_dir / "STATUS.md"
    monkeypatch.setattr(plan, "PLAN", plan_dir)
    monkeypatch.setattr(plan, "STATUS", status_path)
    issues = plan.load_issues()
    status = status or {issue["id"]: {"status": "todo", "link": ""} for issue in issues}
    status_path.write_text(plan.render(issues, status) + "\n")
    return issues, status_path


def test_suffix_ids_and_only_repository_metadata_define_dependencies(monkeypatch, tmp_path):
    issues, _ = configure_plan(
        monkeypatch,
        tmp_path,
        """# Phase 0

## C0.1a First split

Repository: community-base. Depends on: nothing in the package; must land before C0.1b.

Body text. Depends on: R9.9.

## C0.1b Second split

Repository: community-base. Depends on: C0.1a.
""",
    )

    assert [issue["id"] for issue in issues] == ["C0.1a", "C0.1b"]
    assert issues[0]["depends"] == []
    assert issues[1]["depends"] == ["C0.1a"]


def test_check_rejects_duplicate_ids(monkeypatch, tmp_path, capsys):
    configure_plan(
        monkeypatch,
        tmp_path,
        """# Phase 0

## C0.1 Duplicate

Repository: community-base. Depends on: nothing.

## C0.1 Duplicate again

Repository: community-base. Depends on: nothing.
""",
    )

    assert plan.cmd_check() == 1
    assert "duplicate issue ids: C0.1" in capsys.readouterr().out


def test_check_rejects_dependency_cycles(monkeypatch, tmp_path, capsys):
    configure_plan(
        monkeypatch,
        tmp_path,
        """# Phase 0

## C0.1a First

Repository: community-base. Depends on: C0.1b.

## C0.1b Second

Repository: community-base. Depends on: C0.1a.
""",
    )

    assert plan.cmd_check() == 1
    assert "dependency cycles: C0.1a -> C0.1b -> C0.1a" in capsys.readouterr().out


def test_check_rejects_generated_column_drift(monkeypatch, tmp_path, capsys):
    _, status_path = configure_plan(
        monkeypatch,
        tmp_path,
        """# Phase 0

## C0.1 Original title

Repository: community-base. Depends on: nothing.
""",
    )
    status_path.write_text(status_path.read_text().replace("Original title", "Changed title"))

    assert plan.cmd_check() == 1
    assert "STATUS generated columns drift" in capsys.readouterr().out


def test_next_can_select_package_repository(monkeypatch, tmp_path, capsys):
    configure_plan(
        monkeypatch,
        tmp_path,
        """# Phase 0

## C0.1 Package work

Repository: community-base. Depends on: nothing.

## R0.1 Relay work

Repository: DataTalksClub/relay. Depends on: nothing.
""",
    )

    assert plan.cmd_next(repo="community-base") == 0
    output = capsys.readouterr().out
    assert "C0.1" in output
    assert "R0.1" not in output
