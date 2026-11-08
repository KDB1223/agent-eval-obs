"""Self-contained HTML and Markdown summaries of a saved run."""

from __future__ import annotations

import html
from pathlib import Path

from aeo.jsonl import read_jsonl
from aeo.replay.render import render_trajectory

_CSS = """
:root { color-scheme: light dark; }
body { margin: 2rem auto; max-width: 920px; padding: 0 1rem;
       font: 16px/1.5 Georgia, "Iowan Old Style", Palatino, serif; }
h1 { font-size: 1.6rem; margin-bottom: 0.2rem; }
h2 { font-size: 1.15rem; margin-top: 1.6rem; }
.meta, .note { color: #555; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { border-bottom: 1px solid #ccc; text-align: left; padding: 0.35rem 0.5rem; vertical-align: top; white-space: pre-wrap; }
.pass { color: #0a7a32; font-weight: 600; }
.fail { color: #a32020; font-weight: 600; }
.skip { color: #8a5a00; font-weight: 600; }
pre { white-space: pre-wrap; font: 13px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
details { margin: 0.4rem 0 1rem; }
"""


def render_markdown(summary: dict, run_dir: Path) -> str:
    """Markdown scoreboard plus a short transcript for each task."""
    lines = [
        f"# agent-eval-obs report `{summary['run_id']}`",
        "",
        f"- adapter: `{summary.get('adapter', '')}`",
        f"- model: `{summary.get('model', '')}`",
        f"- created: {summary.get('created_at', '')}",
        f"- pass rate: {summary['passed']}/{summary['total']}",
        f"- mean score: {float(summary['mean_score']):.2f}",
        "",
        "| task | category | score | result |",
        "| --- | --- | ---: | --- |",
    ]
    for task in summary["tasks"]:
        flag = "PASS" if task["passed"] else "FAIL"
        lines.append(
            "| {id} | {cat} | {score:.2f} | {flag} |".format(
                id=_md(task["task_id"]),
                cat=_md(str(task.get("category") or "")),
                score=float(task["score"]),
                flag=flag,
            )
        )
    lines.append("")
    for task in summary["tasks"]:
        lines.extend(_markdown_task(task, run_dir))
    return "\n".join(lines).rstrip() + "\n"


def render_html(summary: dict, run_dir: Path) -> str:
    """One HTML file with the scoreboard and each trajectory."""
    rows = []
    for task in summary["tasks"]:
        flag = "PASS" if task["passed"] else "FAIL"
        css = "pass" if task["passed"] else "fail"
        rows.append(
            "<tr>"
            f"<td>{_esc(task['task_id'])}</td>"
            f"<td>{_esc(str(task.get('category') or ''))}</td>"
            f"<td>{float(task['score']):.2f}</td>"
            f"<td class=\"{css}\">{flag}</td>"
            f"<td>{_esc(str(task.get('title') or ''))}</td>"
            "</tr>"
        )
    sections = [_html_task(task, run_dir) for task in summary["tasks"]]
    percent = 0.0
    if summary["total"]:
        percent = 100.0 * int(summary["passed"]) / int(summary["total"])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>agent-eval-obs {_esc(summary['run_id'])}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>agent-eval-obs</h1>
<p class="meta">run {_esc(summary['run_id'])}
· adapter {_esc(str(summary.get('adapter') or ''))}
· model {_esc(str(summary.get('model') or ''))}
· {summary['passed']}/{summary['total']} ({percent:.0f}%)
· mean {float(summary['mean_score']):.2f}</p>
<h2>Scoreboard</h2>
<table>
<thead><tr><th>task</th><th>category</th><th>score</th><th>result</th><th>title</th></tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
<h2>Trajectories</h2>
{''.join(sections)}
<p class="note">Rendered from the JSONL log. The agent was not re-run.</p>
</body>
</html>
"""


def _markdown_task(task: dict, run_dir: Path) -> list[str]:
    flag = "PASS" if task["passed"] else "FAIL"
    lines = [
        f"## {_md(task['task_id'])} · {flag} · {float(task['score']):.2f}",
        "",
        f"{_md(str(task.get('title') or ''))}",
        "",
    ]
    if task.get("error"):
        lines.extend([f"Error: `{_md(str(task['error']))}`", ""])
    if task.get("final_answer"):
        lines.extend(["Final answer:", "", "```", str(task["final_answer"]), "```", ""])
    grades = task.get("grades") or []
    if grades:
        lines.append("| grader | type | result | detail |")
        lines.append("| --- | --- | --- | --- |")
        for grade in grades:
            if grade.get("skipped"):
                result = "SKIP"
            else:
                result = "PASS" if grade.get("passed") else "FAIL"
            detail = str(grade.get("detail") or "").replace("\n", " ")
            lines.append(
                f"| {_md(str(grade.get('id')))} | {_md(str(grade.get('type')))} | {result} | {_md(detail)} |"
            )
        lines.append("")
    transcript = _transcript(run_dir, task["task_id"])
    if transcript:
        lines.extend(["<details>", "", "```", transcript.rstrip(), "```", "", "</details>", ""])
    return lines


def _html_task(task: dict, run_dir: Path) -> str:
    flag = "PASS" if task["passed"] else "FAIL"
    css = "pass" if task["passed"] else "fail"
    grade_rows = []
    for grade in task.get("grades") or []:
        if grade.get("skipped"):
            result, klass = "SKIP", "skip"
        elif grade.get("passed"):
            result, klass = "PASS", "pass"
        else:
            result, klass = "FAIL", "fail"
        grade_rows.append(
            "<tr>"
            f"<td>{_esc(str(grade.get('id')))}</td>"
            f"<td>{_esc(str(grade.get('type')))}</td>"
            f"<td class=\"{klass}\">{result}</td>"
            f"<td>{_esc(str(grade.get('detail') or ''))}</td>"
            "</tr>"
        )
    grades = ""
    if grade_rows:
        grades = (
            "<table><thead><tr><th>grader</th><th>type</th><th>result</th><th>detail</th></tr></thead>"
            f"<tbody>{''.join(grade_rows)}</tbody></table>"
        )
    answer = ""
    if task.get("final_answer"):
        answer = f"<h3>Final answer</h3><pre>{_esc(str(task['final_answer']))}</pre>"
    error = ""
    if task.get("error"):
        error = f"<p class=\"fail\">error: {_esc(str(task['error']))}</p>"
    transcript = _transcript(run_dir, task["task_id"])
    body = f"<pre>{_esc(transcript)}</pre>" if transcript else "<p class=\"note\">No trajectory file.</p>"
    return (
        f"<h2>{_esc(task['task_id'])} <span class=\"{css}\">{flag}</span></h2>"
        f"<p>{_esc(str(task.get('title') or ''))}</p>"
        f"{error}{answer}{grades}"
        f"<details><summary>Trajectory</summary>{body}</details>"
    )


def _transcript(run_dir: Path, task_id: str) -> str:
    path = run_dir / "tasks" / task_id / "trajectory.jsonl"
    if not path.is_file():
        return ""
    return render_trajectory(read_jsonl(path), task_id)


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _md(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
