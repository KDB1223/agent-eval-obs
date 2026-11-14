"""Diff two saved runs by per-task score, category, and pass rate."""

from __future__ import annotations

from aeo.scoreboard import render_table


def compare_runs(left: dict, right: dict) -> dict:
    """Build a JSON-serializable comparison of two ``summary.json`` dicts.

    Tasks stay in left-then-right-only order. A shared task is an improvement
    when its score rises, and a regression when its score falls or it passes
    on the left and fails on the right. A task that exists on only one side
    is neither.
    """
    left_tasks = {task["task_id"]: task for task in left.get("tasks") or []}
    right_tasks = {task["task_id"]: task for task in right.get("tasks") or []}
    order = list(left_tasks)
    for task_id in right_tasks:
        if task_id not in left_tasks:
            order.append(task_id)

    tasks: list[dict] = []
    improvements: list[str] = []
    regressions: list[str] = []
    only_in_a: list[str] = []
    only_in_b: list[str] = []
    for task_id in order:
        before = left_tasks.get(task_id)
        after = right_tasks.get(task_id)
        a_score, a_passed = _side(before)
        b_score, b_passed = _side(after)
        delta: float | None = None
        if before is not None and after is not None:
            delta = float(after["score"]) - float(before["score"])
            if delta > 1e-9:
                improvements.append(task_id)
            passed_then_failed = bool(before["passed"]) and not bool(after["passed"])
            regressed = delta < -1e-9 or passed_then_failed
            if regressed:
                regressions.append(task_id)
        elif before is None:
            only_in_b.append(task_id)
        else:
            only_in_a.append(task_id)
        tasks.append(
            {
                "task_id": task_id,
                "category": _category_name(before, after),
                "a_score": a_score,
                "a_passed": a_passed,
                "b_score": b_score,
                "b_passed": b_passed,
                "delta": delta,
            }
        )

    return {
        "run_a": _run_side(left),
        "run_b": _run_side(right),
        "pass_delta": int(right["passed"]) - int(left["passed"]),
        "mean_delta": float(right["mean_score"]) - float(left["mean_score"]),
        "tasks": tasks,
        "categories": _category_rows(tasks),
        "improvements": improvements,
        "regressions": regressions,
        "only_in_a": only_in_a,
        "only_in_b": only_in_b,
    }


def format_compare(left: dict, right: dict) -> tuple[str, list[str]]:
    """Return the scoreboard text and the list of regressed task ids.

    A regression is a shared task whose score fell, or a task that passed
    on the left and fails on the right. Tasks that exist on only one side
    are listed on their own lines. Category totals follow the overall
    pass rate and mean, and are omitted when neither run has tasks.
    """
    payload = compare_runs(left, right)
    task_rows = [_task_cells(task) for task in payload["tasks"]]
    table = render_table(
        ["task", "A score", "A", "B score", "B", "delta"],
        task_rows,
    )
    run_a = payload["run_a"]
    run_b = payload["run_b"]
    lines = [
        f"compare  {run_a['run_id']}  ->  {run_b['run_id']}",
        f"adapter  {run_a['adapter']}  ->  {run_b['adapter']}",
        "",
        table,
        "",
        (
            f"pass rate     {run_a['passed']}/{run_a['total']}  ->  "
            f"{run_b['passed']}/{run_b['total']}  ({payload['pass_delta']:+d})"
        ),
        (
            f"mean score    {run_a['mean_score']:.2f}  ->  "
            f"{run_b['mean_score']:.2f}  ({payload['mean_delta']:+.2f})"
        ),
    ]
    if payload["categories"]:
        category_rows = [_category_cells(row) for row in payload["categories"]]
        lines.extend(
            [
                "",
                render_table(
                    ["category", "A pass", "A mean", "B pass", "B mean", "delta"],
                    category_rows,
                ),
            ]
        )
    improvements = payload["improvements"]
    regressions = payload["regressions"]
    lines.extend(
        [
            "",
            "improvements  " + (", ".join(improvements) if improvements else "none"),
            "regressions   " + (", ".join(regressions) if regressions else "none"),
        ]
    )
    if payload["only_in_a"]:
        lines.append("only in A     " + ", ".join(payload["only_in_a"]))
    if payload["only_in_b"]:
        lines.append("only in B     " + ", ".join(payload["only_in_b"]))
    lines.append("")
    return "\n".join(lines), list(regressions)


def _run_side(summary: dict) -> dict:
    return {
        "run_id": summary["run_id"],
        "adapter": str(summary.get("adapter") or ""),
        "passed": int(summary["passed"]),
        "total": int(summary["total"]),
        "mean_score": float(summary["mean_score"]),
    }


def _side(task: dict | None) -> tuple[float | None, bool | None]:
    if task is None:
        return None, None
    return float(task["score"]), bool(task["passed"])


def _category_name(before: dict | None, after: dict | None) -> str:
    source = before if before is not None else after
    if source is None:
        return ""
    return str(source.get("category") or "")


def _category_rows(tasks: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for task in tasks:
        buckets.setdefault(str(task["category"]), []).append(task)
    rows: list[dict] = []
    for name, members in buckets.items():
        a_scores = [task["a_score"] for task in members if task["a_score"] is not None]
        b_scores = [task["b_score"] for task in members if task["b_score"] is not None]
        a_passed = sum(1 for task in members if task["a_passed"] is True)
        b_passed = sum(1 for task in members if task["b_passed"] is True)
        a_total = len(a_scores)
        b_total = len(b_scores)
        a_mean = sum(a_scores) / a_total if a_total else None
        b_mean = sum(b_scores) / b_total if b_total else None
        if a_mean is None or b_mean is None:
            mean_delta = None
        else:
            mean_delta = b_mean - a_mean
        rows.append(
            {
                "category": name,
                "a_passed": a_passed,
                "a_total": a_total,
                "a_mean": a_mean,
                "b_passed": b_passed,
                "b_total": b_total,
                "b_mean": b_mean,
                "pass_delta": b_passed - a_passed,
                "mean_delta": mean_delta,
            }
        )
    return rows


def _task_cells(task: dict) -> list[str]:
    return [
        str(task["task_id"]),
        _fmt_score(task["a_score"]),
        _fmt_flag(task["a_passed"]),
        _fmt_score(task["b_score"]),
        _fmt_flag(task["b_passed"]),
        _fmt_task_delta(task["delta"]),
    ]


def _category_cells(row: dict) -> list[str]:
    return [
        str(row["category"]),
        f"{row['a_passed']}/{row['a_total']}",
        _fmt_score(row["a_mean"]),
        f"{row['b_passed']}/{row['b_total']}",
        _fmt_score(row["b_mean"]),
        _fmt_category_delta(row["mean_delta"]),
    ]


def _fmt_score(score: float | None) -> str:
    if score is None:
        return "—"
    return f"{score:.2f}"


def _fmt_flag(passed: bool | None) -> str:
    if passed is None:
        return "—"
    return "PASS" if passed else "FAIL"


def _fmt_task_delta(delta: float | None) -> str:
    if delta is None:
        return "    "
    return f"{delta:+.2f}"


def _fmt_category_delta(delta: float | None) -> str:
    if delta is None:
        return "—"
    return f"{delta:+.2f}"
