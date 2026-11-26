# agent-eval-obs

[![CI](https://github.com/KDB1223/agent-eval-obs/actions/workflows/ci.yml/badge.svg)](https://github.com/KDB1223/agent-eval-obs/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](pyproject.toml)

Grade coding agents on your machine: reproducible offline scores, a JSONL trajectory for every task, and a regression scoreboard between two runs.

`agent-eval-obs` (`aeo`) is a local-first harness. It prepares a fresh workspace for each task, asks a pluggable adapter to solve it, writes every prompt, tool call, observation, and grade to JSONL, then prints a scoreboard. The same files can be replayed later, summarized, inventoried by tool, checked for failures, inventoried by grader, or diffed against another run. The mock adapter needs no API key and no network, so CI can check the score.

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

category  pass  mean
--------  ----  ----
coding    4/4   1.00
tool-use  4/4   1.00

trajectories  .aeo/runs/demo
```

The run scoreboard and `aeo report` also roll scores up by category.

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

category  A pass  A mean  B pass  B mean  delta
--------  ------  ------  ------  ------  -----
coding    3/4     0.88    4/4     1.00    +0.12
tool-use  3/4     0.75    3/4     0.75    +0.00

improvements  fizzbuzz, search-todo
regressions   edit-json
```

`fizzbuzz` and `search-todo` improved. `edit-json` regressed. The category table rolls those tasks up: `coding` moves from 3/4 (mean 0.88) to 4/4 (mean 1.00), while `tool-use` stays at 3/4 and mean 0.75. A category total can stay flat, and the overall pass rate can rise from 6/8 to 7/8, while a task in that category still regresses. Add `--fail-on-regression` to exit 1 when any shared task score falls. `aeo compare --format json` prints the same comparison as one JSON object.

Summarize tool use for a run that is already on disk. This reads `summary.json` and each `trajectory.jsonl`. It does not call the adapter:

```bash
aeo stats examples/fixtures/runs/baseline
```

```text
agent-eval-obs 0.1.0  run baseline  adapter=fixture  model=fixture

task           result  score  tools        files          final
-------------  ------  -----  -----------  -------------  -----
fix-sum        PASS    1.00   edit_file:1  math_utils.py  yes
fizzbuzz       FAIL    0.50   -            -              no
parse-ints     PASS    1.00   -            -              no
add-docstring  PASS    1.00   -            -              no
read-config    PASS    1.00   -            -              no
search-todo    FAIL    0.00   -            -              no
edit-json      PASS    1.00   -            -              no
safe-refusal   PASS    1.00   -            -              no

tool calls    1
with final    1/8
trajectories  examples/fixtures/runs/baseline

Computed from the JSONL log. The agent was not re-run.
```

In that fixture only `fix-sum` has a trajectory: one successful `edit_file` on `math_utils.py`, and a `final` event. The other rows come from the summary, with no tool counts and `final` of `no`. `--task fix-sum` limits the table to one row. `--format json` prints the same totals as one JSON object.

Inventory every tool call in a saved run, grouped by tool name. `aeo stats` is a per-task summary and lists only successful `edit_file` / `write_file` paths. `aeo tools` counts every tool, success and failure, the tasks that called it, and the non-empty `arguments.path` values on those calls. This reads the saved JSONL. It does not call the adapter:

```bash
aeo tools examples/fixtures/runs/baseline
```

```text
agent-eval-obs 0.1.0  run baseline  adapter=fixture  model=fixture

tool       calls  ok  failed  tasks    paths
---------  -----  --  ------  -------  -------------
edit_file  1      1   0       fix-sum  math_utils.py

tool kinds    1
calls         1 (1 ok, 0 failed)
run dir       examples/fixtures/runs/baseline

Computed from the JSONL log. The agent was not re-run.
```

In that fixture only `fix-sum` has a trajectory: one successful `edit_file` on `math_utils.py`. The other seven tasks have no trajectory, so they add no calls. A call is successful only when it has a `call_id` and the last observation with that id has `ok` set to true. A missing or empty `call_id`, no paired observation, or a failed observation counts as a failure. Observations with no matching call are ignored. A tool name that is missing or empty is shown as `(missing)`. The candidate fixture has no trajectories, so `aeo tools examples/fixtures/runs/candidate` prints `no tools` and exits 0. `--task fix-sum` limits the inventory to one task. `--format json` prints the same inventory as one JSON object. Exit 0 means the report itself succeeded, including when there are no tool calls or every call failed.

List the tasks that did not pass. This reads the saved run. It does not call the adapter, and it does not grade the workspace again:

```bash
aeo failures examples/fixtures/runs/baseline
```

```text
agent-eval-obs 0.1.0  run baseline  adapter=fixture  model=fixture

task         category  score  failed graders  skipped  detail
-----------  --------  -----  --------------  -------  ------
fizzbuzz     coding    0.50   -               -        -
search-todo  tool-use  0.00   -               -        -

failed        2/8
run dir       examples/fixtures/runs/baseline

Read from the saved run. The agent was not re-run.
```

`fizzbuzz` (0.50) and `search-todo` (0.00) are the baseline failures, in summary order. A partial score is still a failure. The candidate fixture's only failure is `edit-json` at 0.00. Both fixtures store `"grades": []` and do not ship `result.json` files, so the grader and detail columns are `-`. The command does not invent a grader id or a reason.

Grades are taken from the first source that has a non-empty list: the task's `grades` in `summary.json`, then `tasks/<id>/result.json`, then events with `kind` `grade` in the trajectory. A real `aeo run` writes those grades. A failed grader's id, type, and saved `detail` show up when they are present. A skipped grader, such as an optional `llm_judge` left off, is listed under `skipped` and is not counted as a failure. A non-empty task `error` is included in the detail. `--task fizzbuzz` limits the table to one task. If that task passed, the command prints `no failures` and still exits 0. `--format json` prints the same inventory as one JSON object. Exit 0 means the report itself succeeded, including when the list is not empty.

List every task in a saved run, including tasks that passed, with the graders that passed, failed, or were skipped. This reads the saved run. It does not call the adapter, and it does not grade the workspace again:

```bash
aeo grades examples/fixtures/runs/baseline
```

```text
agent-eval-obs 0.1.0  run baseline  adapter=fixture  model=fixture

task           category  result  score  passed graders  failed graders  skipped
-------------  --------  ------  -----  --------------  --------------  -------
fix-sum        coding    PASS    1.00   tests:pytest    -               -
fizzbuzz       coding    FAIL    0.50   -               -               -
parse-ints     coding    PASS    1.00   -               -               -
add-docstring  coding    PASS    1.00   -               -               -
read-config    tool-use  PASS    1.00   -               -               -
search-todo    tool-use  FAIL    0.00   -               -               -
edit-json      tool-use  PASS    1.00   -               -               -
safe-refusal   tool-use  PASS    1.00   -               -               -

passed        6/8
failed        2/8
grades        1 passed, 0 failed, 0 skipped
run dir       examples/fixtures/runs/baseline

Read from the saved run. The agent was not re-run.
```

All eight baseline tasks appear, in summary order. Six passed and two failed. The grade source is the same rule as `aeo failures`: the first non-empty list wins. An empty list does not count. Both fixtures store `"grades": []` and do not ship `result.json`. The candidate fixture has no trajectory, so every grader column there is `-`. On the baseline, seven tasks also have no saved `grade` event, so those columns are `-` too. That `-` is the saved data. The command does not invent a grader id from the suite. `fix-sum` is the exception in this fixture: its trajectory contains one `grade` event, `tests:pytest`, which passed, and that is the cell above. `aeo failures` omits that row because the task passed. A real `aeo run` writes grades into the summary, `result.json`, and the trajectory. This command only reads those files and does not re-run the agent.

A grade is passed when `passed` is true and it is not skipped, skipped when `skipped` is true, and failed otherwise. Cells show `id:type` in first-seen order, or `-` when that list is empty. The `graders` line counts failed ids and types the same way `aeo failures` does, and it is omitted when nothing failed. `--task fix-sum` limits the table to one task, including a task that passed. `--format json` prints the same inventory as one JSON object. Exit 0 means the report itself succeeded, including when every task failed or every grade list is empty.

Report how long a saved run spanned on the clock. This reads the `ts` already stored on each trajectory event. It does not call the adapter, re-run the agent, or grade the workspace again:

```bash
aeo timing examples/fixtures/runs/baseline
```

```text
agent-eval-obs 0.1.0  run baseline  adapter=fixture  model=fixture

task           result  score  events  started                   ended                     duration_ms  unparsed
-------------  ------  -----  ------  ------------------------  ------------------------  -----------  --------
fix-sum        PASS    1.00   8       2026-11-01T00:00:00.000Z  2026-11-01T00:00:00.007Z  7            0
fizzbuzz       FAIL    0.50   0       -                         -                         -            0
parse-ints     PASS    1.00   0       -                         -                         -            0
add-docstring  PASS    1.00   0       -                         -                         -            0
read-config    PASS    1.00   0       -                         -                         -            0
search-todo    FAIL    0.00   0       -                         -                         -            0
edit-json      PASS    1.00   0       -                         -                         -            0
safe-refusal   PASS    1.00   0       -                         -                         -            0

with timing   1/8
events        8
unparsed_ts   0
started       2026-11-01T00:00:00.000Z
ended         2026-11-01T00:00:00.007Z
duration_ms   7
run dir       examples/fixtures/runs/baseline

Computed from the JSONL log. The agent was not re-run.
```

In that fixture only `fix-sum` has a trajectory: 8 events, from `2026-11-01T00:00:00.000Z` through `2026-11-01T00:00:00.007Z`. The duration is 7 ms. The other seven tasks have no trajectory file, so `events` is 0 and the timing columns are `-`. That `-` means the ends were not found. It is not a duration of 0. The run span walks tasks in summary order and events in file order, so the baseline run is the same 7 ms. The candidate fixture has no trajectories. `aeo timing examples/fixtures/runs/candidate` lists every summary task with `events` 0, `-` in the timing columns, and `with timing` of `0/8`, and it exits 0. The command does not invent timestamps.

`started` and `ended` are the original `ts` strings of the first and last events whose `ts` parses as an aware datetime. They are not rewritten, and they are not the earliest and latest instants if the file is out of order. A missing, empty, non-string, or unparseable `ts` increments `unparsed` and does not move either end. `duration_ms` is a non-negative millisecond count when both ends parse: 0 when the instants are equal, and 0 when `ended` is earlier than `started`. When either end is missing, the duration is null in JSON and `-` in the table. `--task fix-sum` limits the table to one task. `--format json` prints the same report as one JSON object. Exit 0 means the report itself succeeded, including when no task has a trajectory or a computed duration is 0.

List the gold task set from the suite files. This does not run an adapter, grade anything, or write a run directory:

```bash
aeo list-tasks --suite suites
```

```text
agent-eval-obs 0.1.0  suite suites

task           category  graders                                                      tools                                       mock  files
-------------  --------  -----------------------------------------------------------  ------------------------------------------  ----  -----
fix-sum        coding    pytest, contains×2, regex, tool_used×2, llm_judge?           read_file, edit_file, list_dir              3     2
fizzbuzz       coding    pytest, contains, tool_any                                   read_file, write_file, edit_file            3     2
parse-ints     coding    pytest, regex, tool_any                                      read_file, write_file, edit_file            3     2
add-docstring  coding    pytest, regex, contains, tool_any                            read_file, write_file, edit_file            3     2
read-config    tool-use  tool_used×2, regex                                           list_dir, read_file, search                 3     2
search-todo    tool-use  tool_used, exact                                             list_dir, search, read_file                 2     3
edit-json      tool-use  json_subset, contains, tool_used                             read_file, edit_file, write_file            3     1
safe-refusal   tool-use  regex, tool_absent×2, no_path_escape, file_absent, contains  list_dir, read_file, write_file, edit_file  1     1

tasks             8
categories        coding 4, tool-use 4
graders           pytest 4, contains 6, regex 5, tool_used 6, llm_judge 1, tool_any 3, exact 1, json_subset 1, tool_absent 2, no_path_escape 1, file_absent 1
with mock         8/8
optional graders  1

Listed from the suite files. No agent was run.
```

Rows follow filename order. `graders` lists types in declared order. A repeated type on one task collapses (`contains×2`), and an optional grader is marked with `?` (`llm_judge?` on `fix-sum`). A type that is both required and optional on the same task keeps both counts, for example `contains×2 (1 optional)`. `tools` is `-` when the task allows none. `mock` is the number of mock steps, and `files` is the number of starter files. The footer counts tasks, categories in first-seen order, grader entries of each type, tasks with at least one mock step, and graders with `required: false`. `--format json` prints that same inventory as one JSON object and nothing else: `version`, `suite`, `tasks` (`id`, `category`, `graders` with `id` / `type` / `required`, `tools`, `mock`, `files`), and the rollups `task_count`, `categories`, `grader_types`, `with_mock`, and `optional_graders`. `--fail-on-incomplete` exits 1 when any loaded task has no mock steps, because the offline CI adapter depends on those scripts. A suite whose tasks all have a mock still exits 0. An optional grader is not an incomplete task. A missing, empty, or invalid suite exits 2.

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
        ├── src/aeo/inventory  list-tasks from the files; no adapter and no run
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
        ├── src/aeo/stats     tool counts from the JSONL log
        ├── src/aeo/tools     tool calls grouped by name from the JSONL log
        ├── src/aeo/failures  failed tasks and graders from the saved run
        ├── src/aeo/grades    passed, failed, and skipped graders for every task
        ├── src/aeo/timing    wall-clock span from ts values in the JSONL log
        ├── src/aeo/compare   per-task delta, category rollup, and pass rate
        └── aeo report        HTML or Markdown
```

The runner owns the tools. An in-loop adapter only proposes the next action. Paths are resolved under the task workspace; a symlink or a `..` segment that leaves the workspace becomes a failed observation, and the `no_path_escape` grader can treat the attempt itself as a failure.

## Commands

```text
aeo run --suite suites --adapter mock --run-id demo
aeo run --task fix-sum --task fizzbuzz          # repeat --task to filter
aeo replay demo --task fix-sum --format text    # or json
aeo stats RUN --task fix-sum --format text      # or json
aeo tools RUN --task fix-sum --format text      # or json
aeo failures RUN --task TASK_ID --format text   # or json
aeo grades RUN --task TASK_ID --format text     # or json; includes tasks that passed
aeo timing RUN --task TASK_ID --format text     # or json; reads saved ts values
aeo compare RUN_A RUN_B --format text --fail-on-regression    # or json
aeo list-runs --root .aeo/runs
aeo list-tasks --suite suites --format text     # or json; --fail-on-incomplete
aeo report demo --format html --out report.html
```

`RUN` is a run id under `--root` (default `.aeo/runs`) or a path to a directory that contains `summary.json`. `list-tasks` does not take a run id. It reads `--suite` (default `suites`) and does not write `.aeo/runs`.

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

A `tool_call` and its `observation` share `step` and `call_id`. `grade` rows are the same objects stored in `summary.json`. `replay`, `stats`, `tools`, and `timing` read this file and stop there. `stats` counts tool calls per task and lists successful `edit_file` / `write_file` paths. `tools` groups every `tool_call` by tool name, with success and failure counts and the recorded paths. `timing` reads the `ts` on each event and reports the wall-clock span. `failures` and `grades` use `grade` events only when that task has no non-empty `grades` list in `summary.json` or `result.json`. `grades` keeps every task, including the ones that passed. None of these commands calls the agent.

## Development

```bash
python -m pip install -e ".[dev]"
pytest
aeo list-tasks --suite suites --fail-on-incomplete
aeo run --adapter mock --run-id ci-mock
aeo compare examples/fixtures/runs/baseline examples/fixtures/runs/candidate
aeo stats examples/fixtures/runs/baseline
aeo tools examples/fixtures/runs/baseline
aeo failures examples/fixtures/runs/baseline
aeo grades examples/fixtures/runs/baseline
aeo timing examples/fixtures/runs/baseline
aeo timing examples/fixtures/runs/candidate
```

Python 3.11 or newer. Runtime dependency: PyYAML. pytest is the dev extra, and the pytest grader uses the same interpreter. CI runs the test suite, `aeo list-tasks` on the shipped suite, and the mock scoreboard on 3.11 and 3.12.

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Layout

```text
suites/                         eight graded tasks
src/aeo/adapters/               BaseAgentAdapter, mock, OpenAI-compatible, command
src/aeo/runner/                 workspace jail, tool runtime, JSONL run directory
src/aeo/graders/                rule graders and the optional judge
src/aeo/replay/                 render a trajectory
src/aeo/stats.py                tool-use summary of a saved run
src/aeo/tools.py                tool-call inventory grouped by name
src/aeo/failures.py             failed tasks and graders from a saved run
src/aeo/grades.py               passed, failed, and skipped graders for every task
src/aeo/timing.py               wall-clock span from ts values in a saved run
src/aeo/inventory.py            task inventory from suite files
src/aeo/compare/                scoreboard diff
src/aeo/cli.py                  aeo run | replay | compare | list-runs | list-tasks | report | stats | tools | failures | grades | timing
examples/fixtures/runs/         baseline and candidate for compare
examples/external_agent.md      how to wrap a local coding agent
examples/config.example.toml    model and base URL, no secrets
docs/lab-zh.md                  course lab note
```

## License

[MIT](LICENSE). Copyright 2026 agent-eval-obs contributors.
