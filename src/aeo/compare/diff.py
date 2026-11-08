"""Diff two saved runs by per-task score and pass rate."""

from __future__ import annotations


def format_compare(left: dict, right: dict) -> tuple[str, list[str]]:
    """Return the scoreboard text and the list of regressed task ids.

    A regression is a shared task whose score fell, or a task that passed
    on the left and fails on the right. Tasks that exist on only one side
    are listed on their own lines.
    """
    left_tasks = {task["task_id"]: task for task in left.get("tasks") or []}
    right_tasks = {task["task_id"]: task for task in right.get("tasks") or []}
    order = list(left_tasks)
    for task_id in right_tasks:
        if task_id not in left_tasks:
            order.append(task_id)
    rows: list[list[str]] = []
    improvements: list[str] = []
    regressions: list[str] = []
    for task_id in order:
        before = left_tasks.get(task_id)
        after = right_tasks.get(task_id)
        if before is None or after is None:
            rows.append(
                [
                    task_id,
                    _score(before),
                    _flag(before),
                    _score(after),
                    _flag(after),
                    "    ",
                ]
            )
            continue
        delta = float(after["score"]) - float(before["score"])
        rows.append(
            [
                task_id,
                f"{float(before['score']):.2f}",
                "PASS" if before["passed"] else "FAIL",
                f"{float(after['score']):.2f}",
                "PASS" if after["passed"] else "FAIL",
                f"{delta:+.2f}",
            ]
        )
        if delta > 1e-9:
            improvements.append(task_id)
        regressed = delta < -1e-9 or (before["passed"] and not after["passed"])
        if regressed:
            regressions.append(task_id)
    from aeo.scoreboard import render_table

    table = render_table(
        ["task", "A score", "A", "B score", "B", "delta"],
        rows,
    )
    pass_delta = int(right["passed"]) - int(left["passed"])
    mean_delta = float(right["mean_score"]) - float(left["mean_score"])
    only_left = [task_id for task_id in left_tasks if task_id not in right_tasks]
    only_right = [task_id for task_id in right_tasks if task_id not in left_tasks]
    lines = [
        f"compare  {left['run_id']}  ->  {right['run_id']}",
        f"adapter  {left.get('adapter', '')}  ->  {right.get('adapter', '')}",
        "",
        table,
        "",
        (
            f"pass rate     {left['passed']}/{left['total']}  ->  "
            f"{right['passed']}/{right['total']}  ({pass_delta:+d})"
        ),
        (
            f"mean score    {float(left['mean_score']):.2f}  ->  "
            f"{float(right['mean_score']):.2f}  ({mean_delta:+.2f})"
        ),
        "",
        "improvements  " + (", ".join(improvements) if improvements else "none"),
        "regressions   " + (", ".join(regressions) if regressions else "none"),
    ]
    if only_left:
        lines.append("only in A     " + ", ".join(only_left))
    if only_right:
        lines.append("only in B     " + ", ".join(only_right))
    lines.append("")
    return "\n".join(lines), regressions


def _score(task: dict | None) -> str:
    if task is None:
        return "—"
    return f"{float(task['score']):.2f}"


def _flag(task: dict | None) -> str:
    if task is None:
        return "—"
    return "PASS" if task["passed"] else "FAIL"
