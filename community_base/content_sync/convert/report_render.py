"""The change and inventory sections shared by conversion reports."""


def render_changes(report, lines: list[str]) -> None:
    heading = "## changes"
    if not report.applied:
        heading = "## proposed changes (dry run; no files written)"
    lines.append(heading)
    for change in report.changes:
        if change.action != "unchanged":
            lines.append(change.render())
    lines.append("")
    problems = report.verify()
    lines.append("## inventory")
    if problems:
        lines.extend(f"  UNACCOUNTED {problem}" for problem in problems)
    else:
        lines.append("  every file before the conversion is accounted for after it")
