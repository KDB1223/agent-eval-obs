"""Plain-text tables for the run scoreboard and the compare view."""

from __future__ import annotations

from aeo import __version__


def render_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a left-aligned monospace table."""
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def format_row(row: list[str]) -> str:
        padded = [cell.ljust(widths[index]) for index, cell in enumerate(row)]
        return "  ".join(padded).rstrip()

    rule = ["-" * width for width in widths]
    lines = [format_row(headers), format_row(rule)]
    lines.extend(format_row(row) for row in rows)
    return "\n".join(lines)


def category_totals(tasks: list[dict]) -> list[dict]:
    """Pass count and unweighted mean score for each category.

    Categories stay in first-seen order. A missing or empty category is
    an empty string, and an empty task list returns no rows.
    """
    buckets: dict[str, list[dict]] = {}
    for task in tasks:
        name = str(task.get("category") or "")
        buckets.setdefault(name, []).append(task)
    rows: list[dict] = []
    for name, members in buckets.items():
        scores = [float(task["score"]) for task in members]
        passed = sum(1 for task in members if bool(task["passed"]))
        total = len(members)
        rows.append(
            {
                "category": name,
                "passed": passed,
                "total": total,
                "mean": sum(scores) / total,
            }
        )
    return rows


def format_scoreboard(summary: dict) -> str:
    """Render the human scoreboard stored next to a run."""
    rows: list[list[str]] = []
    for task in summary["tasks"]:
        rows.append(
            [
                str(task["task_id"]),
                str(task.get("category") or "task"),
                f"{float(task['score']):.2f}",
                "PASS" if task["passed"] else "FAIL",
            ]
        )
    table = render_table(["task", "category", "score", "result"], rows)
    passed = int(summary["passed"])
    total = int(summary["total"])
    percent = (100.0 * passed / total) if total else 0.0
    run_dir = summary.get("run_dir") or ""
    lines = [
        (
            f"agent-eval-obs {__version__}  "
            f"run {summary['run_id']}  "
            f"adapter={summary['adapter']}  "
            f"model={summary.get('model') or summary['adapter']}"
        ),
        "",
        table,
        "",
        f"pass rate     {passed}/{total} ({percent:.0f}%)",
        f"mean score    {float(summary['mean_score']):.2f}",
    ]
    totals = category_totals(summary["tasks"])
    if totals:
        category_rows = [
            [row["category"], f"{row['passed']}/{row['total']}", f"{row['mean']:.2f}"]
            for row in totals
        ]
        lines.extend(["", render_table(["category", "pass", "mean"], category_rows), ""])
    lines.extend([f"trajectories  {run_dir}", ""])
    return "\n".join(lines)
