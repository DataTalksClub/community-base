from pathlib import Path

import scripts.plan as plan


def configure_plan(monkeypatch, tmp_path: Path, phase_text: str, status=None, decisions_text=""):
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    (plan_dir / "phase-0.md").write_text(phase_text)
    status_path = plan_dir / "STATUS.md"
    decisions_path = tmp_path / "01-decisions.md"
    monkeypatch.setattr(plan, "PLAN", plan_dir)
    monkeypatch.setattr(plan, "STATUS", status_path)
    monkeypatch.setattr(plan, "DECISIONS", decisions_path)
    decisions_path.write_text(decisions_text)
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


def test_two_letter_suffix_ids(monkeypatch, tmp_path):
    issues, _ = configure_plan(
        monkeypatch,
        tmp_path,
        """# Phase 0

## C0.1da First part of a split issue

Repository: community-base. Depends on: nothing.

## C0.1db Second part of a split issue

Repository: community-base. Depends on: C0.1da.

## C0.2 Later issue

Repository: community-base. Depends on: C0.1db.
""",
    )

    assert [issue["id"] for issue in issues] == ["C0.1da", "C0.1db", "C0.2"]
    assert issues[1]["depends"] == ["C0.1da"]
    assert issues[2]["depends"] == ["C0.1db"]


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


def test_check_rejects_done_issue_with_unfinished_dependency(monkeypatch, tmp_path, capsys):
    phase_text = """# Phase 0

## C0.1a First

Repository: community-base. Depends on: nothing.

## C0.1b Second

Repository: community-base. Depends on: C0.1a.
"""
    configure_plan(
        monkeypatch,
        tmp_path,
        phase_text,
        status={
            "C0.1a": {"status": "in-progress", "link": ""},
            "C0.1b": {"status": "done", "link": ""},
        },
    )

    assert plan.cmd_check() == 1
    assert (
        "done issues with a dependency that is not done or skipped: "
        "C0.1b depends on C0.1a (in-progress)" in capsys.readouterr().out
    )


def test_check_reports_every_done_issue_with_an_unfinished_dependency(
    monkeypatch, tmp_path, capsys
):
    phase_text = """# Phase 0

## C0.1a First

Repository: community-base. Depends on: nothing.

## C0.1b Second

Repository: community-base. Depends on: C0.1a.

## C0.2a Third

Repository: community-base. Depends on: nothing.

## C0.2b Fourth

Repository: community-base. Depends on: C0.2a.
"""
    configure_plan(
        monkeypatch,
        tmp_path,
        phase_text,
        status={
            "C0.1a": {"status": "in-progress", "link": ""},
            "C0.1b": {"status": "done", "link": ""},
            "C0.2a": {"status": "blocked", "link": ""},
            "C0.2b": {"status": "done", "link": ""},
        },
    )

    assert plan.cmd_check() == 1
    output = capsys.readouterr().out
    assert "C0.1b depends on C0.1a (in-progress)" in output
    assert "C0.2b depends on C0.2a (blocked)" in output


def test_check_accepts_done_issue_once_its_dependency_is_done(monkeypatch, tmp_path, capsys):
    phase_text = """# Phase 0

## C0.1a First

Repository: community-base. Depends on: nothing.

## C0.1b Second

Repository: community-base. Depends on: C0.1a.
"""
    configure_plan(
        monkeypatch,
        tmp_path,
        phase_text,
        status={
            "C0.1a": {"status": "done", "link": ""},
            "C0.1b": {"status": "done", "link": ""},
        },
    )

    assert plan.cmd_check() == 0
    assert "OK: 2 issues, STATUS.md consistent" in capsys.readouterr().out


def test_check_warns_on_blocked_row_citing_a_now_done_blocker(monkeypatch, tmp_path, capsys):
    phase_text = """# Phase 0

## C0.1 First

Repository: community-base. Depends on: nothing.

## C0.2 Second

Repository: community-base. Depends on: nothing.
"""
    configure_plan(
        monkeypatch,
        tmp_path,
        phase_text,
        status={
            "C0.1": {"status": "done", "link": ""},
            "C0.2": {"status": "blocked", "link": "blocked on C0.1 landing"},
        },
    )

    assert plan.cmd_check() == 0
    output = capsys.readouterr().out
    assert "warning: C0.2 is blocked, citing C0.1, which is now done" in output
    assert "OK:" not in output


def test_check_does_not_warn_while_the_cited_blocker_is_still_open(monkeypatch, tmp_path, capsys):
    phase_text = """# Phase 0

## C0.1 First

Repository: community-base. Depends on: nothing.

## C0.2 Second

Repository: community-base. Depends on: nothing.
"""
    configure_plan(
        monkeypatch,
        tmp_path,
        phase_text,
        status={
            "C0.1": {"status": "in-progress", "link": ""},
            "C0.2": {"status": "blocked", "link": "blocked on C0.1 landing"},
        },
    )

    assert plan.cmd_check() == 0
    output = capsys.readouterr().out
    assert "warning:" not in output
    assert "OK: 2 issues, STATUS.md consistent" in output


def test_check_rejects_decision_landing_on_unknown_issue(monkeypatch, tmp_path, capsys):
    phase_text = """# Phase 0

## C0.1 First

Repository: community-base. Depends on: nothing.
"""
    decisions_text = (
        "# Decisions\n\n"
        "| # | Decision | Consequence for the plan |\n"
        "|---|---|---|\n"
        "| D1 | A rule that requires code. | Lands in: `C0.99`. |\n"
    )
    configure_plan(monkeypatch, tmp_path, phase_text, decisions_text=decisions_text)

    assert plan.cmd_check() == 1
    assert "decisions naming an issue that does not exist: D1 names unknown issue C0.99" in (
        capsys.readouterr().out
    )


def test_check_accepts_decision_landing_on_a_real_issue(monkeypatch, tmp_path, capsys):
    phase_text = """# Phase 0

## C0.1 First

Repository: community-base. Depends on: nothing.
"""
    decisions_text = (
        "# Decisions\n\n"
        "| # | Decision | Consequence for the plan |\n"
        "|---|---|---|\n"
        "| D1 | A rule that requires code. | Lands in: `C0.1`. |\n"
    )
    configure_plan(monkeypatch, tmp_path, phase_text, decisions_text=decisions_text)

    assert plan.cmd_check() == 0
    assert "OK: 1 issues, STATUS.md consistent" in capsys.readouterr().out


def test_check_accepts_a_decision_declared_to_land_nothing(monkeypatch, tmp_path, capsys):
    phase_text = """# Phase 0

## C0.1 First

Repository: community-base. Depends on: nothing.
"""
    decisions_text = (
        "# Decisions\n\n"
        "| # | Decision | Consequence for the plan |\n"
        "|---|---|---|\n"
        "| D1 | A rule that lands nothing. | Lands in: none. |\n"
    )
    configure_plan(monkeypatch, tmp_path, phase_text, decisions_text=decisions_text)

    assert plan.cmd_check() == 0
    assert "OK: 1 issues, STATUS.md consistent" in capsys.readouterr().out


def test_check_accepts_a_decision_that_lands_in_a_site_tracker(monkeypatch, tmp_path, capsys):
    # A decision can land somewhere this plan does not track: D35 governs credentials in a site's
    # own production database. Writing `none` for one of those would say it lands nothing, which
    # is false, so `site-owned` is a third value and the site's issue is named for a reader.
    phase_text = """# Phase 0

## C0.1 First

Repository: community-base. Depends on: nothing.
"""
    decisions_text = (
        "# Decisions\n\n"
        "| # | Decision | Consequence for the plan |\n"
        "|---|---|---|\n"
        "| D1 | A rule the site owns. | Lands in: site-owned, AI-Shipping-Labs/website#1656. |\n"
    )
    configure_plan(monkeypatch, tmp_path, phase_text, decisions_text=decisions_text)

    assert plan.cmd_check() == 0
    assert "OK: 1 issues, STATUS.md consistent" in capsys.readouterr().out


def test_check_ignores_a_decision_with_no_lands_in_field(monkeypatch, tmp_path, capsys):
    phase_text = """# Phase 0

## C0.1 First

Repository: community-base. Depends on: nothing.
"""
    decisions_text = (
        "# Decisions\n\n"
        "| # | Decision | Consequence for the plan |\n"
        "|---|---|---|\n"
        "| D1 | Article storage stays site-owned. | No issue; not every decision lands code. |\n"
    )
    configure_plan(monkeypatch, tmp_path, phase_text, decisions_text=decisions_text)

    assert plan.cmd_check() == 0
    assert "OK: 1 issues, STATUS.md consistent" in capsys.readouterr().out


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
