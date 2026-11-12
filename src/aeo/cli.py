"""Command-line interface: run, replay, compare, list-runs, report, stats."""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from aeo import __version__
from aeo.adapters.factory import build_adapter
from aeo.compare.diff import format_compare
from aeo.errors import AeoError, UsageError
from aeo.graders.llm_judge import LLMJudge, judge_enabled_from_env
from aeo.replay.render import render_run
from aeo.report import render_html, render_markdown
from aeo.runner.execute import run_suite
from aeo.runner.store import load_summary, resolve_run
from aeo.scoreboard import render_table
from aeo.stats import render_stats


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch a subcommand. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except AeoError as exc:
        print(f"aeo: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("aeo: interrupted", file=sys.stderr)
        return 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aeo",
        description="Evaluate coding agents, record trajectories, and compare runs.",
    )
    parser.add_argument("--version", action="version", version=f"aeo {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="grade a task suite and write a run directory")
    run.add_argument("--suite", default="suites", help="directory of task YAML files (default: suites)")
    run.add_argument("--adapter", default="mock", choices=["mock", "openai", "command"])
    run.add_argument("--run-id", default=None, help="directory name under the runs root")
    run.add_argument("--root", default=".aeo/runs", help="where runs are stored")
    run.add_argument("--task", action="append", default=None, help="run one task id (repeatable)")
    run.add_argument("--force", action="store_true", help="replace an existing run id")
    run.add_argument("--llm-judge", action="store_true", help="enable the optional model grader")
    run.add_argument("--config", default=None, help="TOML file with model and base_url")
    run.add_argument("--model", default=None, help="model name for the openai adapter and the judge")
    run.add_argument("--command", action="append", default=None, help="argv item for the command adapter")
    run.add_argument(
        "--ingest-glob",
        default=None,
        help="workspace-relative glob of JSONL logs to copy into the trajectory",
    )
    run.set_defaults(func=_cmd_run)

    replay = commands.add_parser("replay", help="print a trajectory from JSONL")
    replay.add_argument("run", help="run id or path to a run directory")
    replay.add_argument("--task", default=None, help="one task id")
    replay.add_argument("--root", default=".aeo/runs")
    replay.add_argument("--format", choices=["text", "json"], default="text")
    replay.set_defaults(func=_cmd_replay)

    compare = commands.add_parser("compare", help="diff two runs")
    compare.add_argument("run_a", help="baseline run id or path")
    compare.add_argument("run_b", help="candidate run id or path")
    compare.add_argument("--root", default=".aeo/runs")
    compare.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="exit 1 when any shared task score falls",
    )
    compare.set_defaults(func=_cmd_compare)

    listing = commands.add_parser("list-runs", help="list saved runs")
    listing.add_argument("--root", default=".aeo/runs")
    listing.set_defaults(func=_cmd_list)

    report = commands.add_parser("report", help="write an HTML or Markdown summary")
    report.add_argument("run", help="run id or path to a run directory")
    report.add_argument("--format", choices=["html", "md"], default="html")
    report.add_argument("--out", default=None, help="output path, or - for stdout")
    report.add_argument("--root", default=".aeo/runs")
    report.set_defaults(func=_cmd_report)

    stats = commands.add_parser("stats", help="summarize tool use from a saved run")
    stats.add_argument("run", help="run id or path to a run directory")
    stats.add_argument("--task", default=None, help="one task id")
    stats.add_argument("--root", default=".aeo/runs")
    stats.add_argument("--format", choices=["text", "json"], default="text")
    stats.set_defaults(func=_cmd_stats)
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    config = _load_config(args.config)
    if "api_key" in config or "api_token" in config:
        print("aeo: ignoring api_key in the config file; set OPENAI_API_KEY instead", file=sys.stderr)
    model = args.model or _config_str(config, "model")
    base_url = _config_str(config, "base_url")
    adapter = build_adapter(
        args.adapter,
        command=args.command,
        model=model,
        base_url=base_url,
        ingest_glob=args.ingest_glob,
    )
    judge = None
    if args.llm_judge or judge_enabled_from_env():
        judge = LLMJudge.from_env(model=model, base_url=base_url)
    summary = run_suite(
        Path(args.suite),
        adapter,
        run_root=Path(args.root),
        run_id=args.run_id,
        task_ids=args.task,
        force=args.force,
        judge=judge,
    )
    if summary["passed"] == summary["total"]:
        return 0
    return 1


def _cmd_replay(args: argparse.Namespace) -> int:
    run_dir = resolve_run(args.run, args.root)
    sys.stdout.write(render_run(run_dir, task_id=args.task, fmt=args.format))
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    left = load_summary(resolve_run(args.run_a, args.root))
    right = load_summary(resolve_run(args.run_b, args.root))
    text, regressions = format_compare(left, right)
    sys.stdout.write(text)
    if args.fail_on_regression and regressions:
        return 1
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    root = Path(args.root)
    runs = []
    if root.is_dir():
        for child in root.iterdir():
            summary_path = child / "summary.json"
            if child.is_dir() and summary_path.is_file():
                runs.append(load_summary(child))
    if not runs:
        print("no runs")
        return 0
    runs.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    rows = []
    for item in runs:
        rows.append(
            [
                str(item.get("run_id") or ""),
                str(item.get("adapter") or ""),
                f"{item.get('passed')}/{item.get('total')}",
                f"{float(item.get('mean_score') or 0):.2f}",
                str(item.get("created_at") or ""),
            ]
        )
    print(render_table(["run_id", "adapter", "pass", "mean", "created"], rows))
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    run_dir = resolve_run(args.run, args.root)
    summary = load_summary(run_dir)
    if args.format == "html":
        body = render_html(summary, run_dir)
        destination = Path(args.out) if args.out and args.out != "-" else run_dir / "report.html"
    else:
        body = render_markdown(summary, run_dir)
        destination = Path(args.out) if args.out and args.out != "-" else None
    if args.out == "-" or (args.format == "md" and destination is None):
        sys.stdout.write(body)
        return 0
    assert destination is not None
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(body, encoding="utf-8")
    print(destination, file=sys.stderr)
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    run_dir = resolve_run(args.run, args.root)
    summary = load_summary(run_dir)
    sys.stdout.write(render_stats(summary, run_dir, task_id=args.task, fmt=args.format))
    return 0


def _load_config(path: str | None) -> dict:
    if not path:
        return {}
    file_path = Path(path)
    if not file_path.is_file():
        raise UsageError(f"config not found: {path}")
    with file_path.open("rb") as handle:
        data = tomllib.load(handle)
    if not isinstance(data, dict):
        raise UsageError(f"config must be a table: {path}")
    return data


def _config_str(config: dict, key: str) -> str | None:
    value = config.get(key)
    if value is None:
        return None
    return str(value)
