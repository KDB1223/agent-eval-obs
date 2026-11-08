# agent-eval-obs

[![CI](https://github.com/KDB1223/agent-eval-obs/actions/workflows/ci.yml/badge.svg)](https://github.com/KDB1223/agent-eval-obs/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](pyproject.toml)

Grade coding agents on your machine: reproducible offline scores, a JSONL trajectory for every task, and a regression scoreboard between two runs.

`agent-eval-obs` (`aeo`) is a local-first harness. It prepares a fresh workspace for each task, asks a pluggable adapter to solve it, writes every prompt, tool call, observation, and grade to JSONL, then prints a scoreboard. The same files can be replayed later or diffed against another run. The mock adapter needs no API key and no network, so CI can check the score.

中文说明：[README.zh-CN.md](README.zh-CN.md)。课程实验：[docs/lab-zh.md](docs/lab-zh.md)。

## Quickstart

From a clean checkout, well under a minute:

```bash
git clone https://github.com/KDB1223/agent-eval-obs.git
cd agent-eval-obs
python -m pip install -e ".[dev]"
aeo run --adapter mock --run-id demo
```

If `aeo` is not on `PATH`, use `python -m aeo`.

Stdout is the scoreboard (progress lines go to stderr):

```text
agent-eval-obs 0.1.0  run demo  adapter=mock  model=mock-script

task           category  score  result
-------------  --------  -----  ------
fix-sum        coding    1.00   PASS
fizzbuzz       coding    1.00   PASS
parse-ints     coding    1.00   PASS
add-docstring  coding    1.00   PASS
read-config    tool-use  1.00   PASS
search-todo    tool-use  1.00   PASS
edit-json      tool-use  1.00   PASS
safe-refusal   tool-use  1.00   PASS

pass rate     8/8 (100%)
mean score    1.00
trajectories  .aeo/runs/demo
```

That `8/8` is the offline contract. The mock adapter replays the `mock:` script stored in each task file, the runner really executes the tools, and the graders score the workspace. A second run with the same suite produces the same per-task scores.

Replay one trajectory. This prints the log. It does not call the agent again:

```bash
aeo replay demo --task fix-sum
```

The tool trace looks like this (the command also prints one `[grade]` line per check; with the judge left off, `llm_judge` is `SKIP` and the task still scores 1.00):

```text
# task fix-sum

[prompt]
math_utils.py implements add() with subtraction. Change it so add(a, b)
returns the sum of its arguments. Keep the function signature.

[step 1 thought]
I will read math_utils.py before changing it.

[step 1 tool_call] read_file {"path": "math_utils.py"}
[step 1 observation] read_file ok
math_utils.py  lines 1-2 of 2
   1| def add(a, b):
   2|     return a - b

[step 2 thought]
The body subtracts. I will switch that operator to addition.

[step 2 tool_call] edit_file {"new": "return a + b", "old": "return a - b", "path": "math_utils.py"}
[step 2 observation] edit_file ok
updated math_utils.py (1 replacement)

[step 3 thought]
The signature is unchanged and the tests cover the sum.

[final]
add() now returns the sum of its arguments.

[task_end] PASS score=1.00

# replay complete (events printed from the log; the agent was not re-run)
```

Compare a saved baseline with a candidate. The fixture pair below is checked in, so this works before you have two runs of your own:

```bash
aeo compare examples/fixtures/runs/baseline examples/fixtures/runs/candidate
```

```text
compare  baseline  ->  candidate
adapter  fixture  ->  fixture

task           A score  A     B score  B     delta
-------------  -------  ----  -------  ----  -----
fix-sum        1.00     PASS  1.00     PASS  +0.00
fizzbuzz       0.50     FAIL  1.00     PASS  +0.50
parse-ints     1.00     PASS  1.00     PASS  +0.00
add-docstring  1.00     PASS  1.00     PASS  +0.00
read-config    1.00     PASS  1.00     PASS  +0.00
search-todo    0.00     FAIL  1.00     PASS  +1.00
edit-json      1.00     PASS  0.00     FAIL  -1.00
safe-refusal   1.00     PASS  1.00     PASS  +0.00

pass rate     6/8  ->  7/8  (+1)
mean score    0.81  ->  0.88  (+0.06)

improvements  fizzbuzz, search-todo
regressions   edit-json
```

`fizzbuzz` and `search-todo` improved. `edit-json` regressed. Pass rate and mean score move on their own, so a higher pass rate can still hide a regression. Add `--fail-on-regression` to exit 1 when any shared task score falls.

Write a one-file HTML report, or a Markdown summary on stdout:

```bash
aeo report demo --format html --out report.html
aeo report demo --format md
aeo list-runs
```

## What a run records

Each invocation writes `.aeo/runs/<run_id>/`:

```text
manifest.json
summary.json
scoreboard.txt
tasks/<task-id>/trajectory.jsonl
tasks/<task-id>/result.json
tasks/<task-id>/workspace/    # the files the agent left behind
```

`aeo run` exits 0 when every task passes and 1 when any required grader fails. Exit 2 means a bad flag, a missing suite, or an unknown run id.

A task score is the weighted mean of the graders that actually ran. The optional LLM judge is skipped unless you opt in, and a skipped grader is left out of that mean, so the offline `8/8` does not depend on a network call. Pass rate counts tasks whose required graders all passed. Mean score is the unweighted mean of the task scores.

## Architecture

```text
suites/*.yaml                 task prompt, starter files, graders, mock script
        │
        ▼
src/aeo/runner                seed a jailed workspace, loop until a final answer
        │
        ├── src/aeo/adapters  mock | openai | command
        ├── tool runtime      read, write, edit, list, search
        └── JSONL recorder
        │
        ▼
src/aeo/graders               exact, contains, regex, pytest, JSON, tool use, judge
        │
        ▼
.aeo/runs/<run_id>/
        │
        ├── src/aeo/replay    print the trajectory
        ├── src/aeo/compare   per-task delta and pass rate
        └── aeo report        HTML or Markdown
```

The runner owns the tools. An in-loop adapter only proposes the next action. Paths are resolved under the task workspace; a symlink or a `..` segment that leaves the workspace becomes a failed observation, and the `no_path_escape` grader can treat the attempt itself as a failure.

## Commands

```text
aeo run --suite suites --adapter mock --run-id demo
aeo run --task fix-sum --task fizzbuzz          # repeat --task to filter
aeo replay demo --task fix-sum --format text    # or json
aeo compare RUN_A RUN_B --fail-on-regression
aeo list-runs --root .aeo/runs
aeo report demo --format html --out report.html
```

`RUN` is a run id under `--root` (default `.aeo/runs`) or a path to a directory that contains `summary.json`.

## Tasks

Eight tasks ship in `suites/`. Filename order is run order.

| Task | Category | What the agent has to do |
| --- | --- | --- |
| `fix-sum` | coding | Change `add()` from subtraction to addition. Pytest checks the result. |
| `fizzbuzz` | coding | Fill in `fizzbuzz(n)`. |
| `parse-ints` | coding | Skip tokens that `int()` cannot parse. |
| `add-docstring` | coding | Add a docstring that mentions greeting and name. |
| `read-config` | tool-use | Read a JSON config and report port 4815. |
| `search-todo` | tool-use | Search for a TODO and answer with the relative path. |
| `edit-json` | tool-use | Set `debug` to false without touching the other fields. |
| `safe-refusal` | tool-use | Refuse to write `/tmp/...` or `../escape.txt`. |

Each file is one task: `prompt`, starter `files`, allowed `tools`, `graders`, and a `mock` script. The mock script is the offline agent. It is data, so the score stays stable in CI.

## Graders

| Type | Checks |
| --- | --- |
| `exact` | File or final answer equals `value`. |
| `contains` | Substring of a file or the final answer. |
| `regex` | Regular expression against a file or the final answer. |
| `pytest` | Runs pytest on a path inside the task workspace. Pass means exit 0. |
| `json_subset` | A JSON file contains the `expect` object. |
| `tool_used` | The named tool was called at least `min_count` times. |
| `tool_any` | At least one of `tools` was called. |
| `tool_absent` | The named tool was never called. |
| `file_absent` | A relative path does not exist after the run. |
| `no_path_escape` | No tool argument resolves outside the workspace. |
| `llm_judge` | Optional model score in `[0, 1]`. Skipped unless enabled. |

`target` is `file` or `answer`. A grader with `required: false` can lower the task score while the task still passes. `fix-sum` uses that for the judge.

Enable the judge for a live run:

```bash
export OPENAI_API_KEY="sk-..."
export AEO_LLM_JUDGE=1
# optional: export OPENAI_BASE_URL="https://api.openai.com/v1"
# optional: export OPENAI_MODEL="gpt-4o-mini"
aeo run --adapter openai --llm-judge
```

`--config examples/config.example.toml` may set `model` and `base_url`. A key written in that file is ignored. The trajectory records the model name and the tool trace. It does not record the API key.

## Adapters

| Adapter | Role |
| --- | --- |
| `mock` | Replays each task's `mock:` script. Deterministic. This is the CI adapter. |
| `openai` | OpenAI-compatible `POST {base_url}/chat/completions` with the built-in tools. |
| `command` | Runs an external program. The prompt is stdin. `{workspace}`, `{task_id}`, and `{prompt}` are substituted in argv. There is no shell. |

`MockAgentAdapter` and `OpenAICompatibleAgentAdapter` implement `step()`. The runner executes tools and appends observations. `CommandAgentAdapter` owns the loop: the external program edits the workspace itself.

### Coding agents, including dm-code-agent

This harness evaluates agents. A local coding agent edits a workspace and, if it is built for audit, writes its own session log. [dm-code-agent](https://github.com/KDB1223/dm-code-agent) is one such agent: a ReAct loop, workspace tools, and an append-only JSONL session. You can point the command adapter at it when that project is installed:

```bash
aeo run --adapter command \
  --command python --command -m --command dm_agent \
  --command run --command - \
  --command --workspace --command {workspace} \
  --ingest-glob '.dm-agent/sessions/*.jsonl'
```

`run -` reads the task from stdin. `--ingest-glob` copies that agent's JSONL into the aeo trajectory as `external` events, so the original log stays intact and this harness still has one file to replay. The demo does not clone or import dm-code-agent. `aeo run --adapter mock` is the whole offline path.

The same command shape wraps any other local program that reads a prompt, edits the current workspace, and prints a final answer. Details and a short `BaseAgentAdapter` sketch are in [examples/external_agent.md](examples/external_agent.md).

In-loop adapters record every tool call this runner performed. A command adapter records the process boundary plus whatever JSONL you ingest. Both write a run directory that `aeo compare` can diff, which is how a prompt change or a model change becomes a scoreboard instead of a feeling.

## Trajectory

Each line of `trajectory.jsonl` is one JSON object. `kind` is one of:

`task_start`, `prompt`, `thought`, `tool_call`, `observation`, `final`, `grade`, `task_end`, `error`, `external_start`, `external`.

A `tool_call` and its `observation` share `step` and `call_id`. `grade` rows are the same objects stored in `summary.json`. `replay` reads this file and stops there.

## Development

```bash
python -m pip install -e ".[dev]"
pytest
aeo run --adapter mock --run-id ci-mock
aeo compare examples/fixtures/runs/baseline examples/fixtures/runs/candidate
```

Python 3.11 or newer. Runtime dependency: PyYAML. pytest is the dev extra, and the pytest grader uses the same interpreter. CI runs the test suite and the mock scoreboard on 3.11 and 3.12.

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Layout

```text
suites/                         eight graded tasks
src/aeo/adapters/               BaseAgentAdapter, mock, OpenAI-compatible, command
src/aeo/runner/                 workspace jail, tool runtime, JSONL run directory
src/aeo/graders/                rule graders and the optional judge
src/aeo/replay/                 render a trajectory
src/aeo/compare/                scoreboard diff
src/aeo/cli.py                  aeo run | replay | compare | list-runs | report
examples/fixtures/runs/         baseline and candidate for compare
examples/external_agent.md      how to wrap a local coding agent
examples/config.example.toml    model and base URL, no secrets
docs/lab-zh.md                  course lab note
```

## License

[MIT](LICENSE). Copyright 2026 agent-eval-obs contributors.
