# agent-eval-obs

[![CI](https://github.com/KDB1223/agent-eval-obs/actions/workflows/ci.yml/badge.svg)](https://github.com/KDB1223/agent-eval-obs/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](pyproject.toml)

在本机给编程智能体打分：离线分数可复现，每个任务留下 JSONL 轨迹，两次运行可以做成回归记分板。

`agent-eval-obs`（命令名 `aeo`）是一个本地优先的评测工具。它为每个任务准备一块新的工作区，调用可替换的适配器去解题，把提示、工具调用、观察和评分逐行写入 JSONL，然后打印记分板。同一份记录可以事后回放、汇总、列出失败、按评分器列成清单，也可以和另一次运行对比。Mock 适配器不需要 API key，也不需要网络，因此 CI 可以直接核对分数。

English: [README.md](README.md). 课程实验说明：[docs/lab-zh.md](docs/lab-zh.md).

## 一分钟开始

```bash
git clone https://github.com/KDB1223/agent-eval-obs.git
cd agent-eval-obs
python -m pip install -e ".[dev]"
aeo run --adapter mock --run-id demo
```

如果 `aeo` 不在 `PATH` 上，用 `python -m aeo`。标准输出是记分板，进度写在标准错误：

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

单次运行的记分板和 `aeo report` 也会按类别汇总分数。

这行 `8/8` 是离线约定。Mock 适配器按每个任务文件里的 `mock:` 脚本走，运行器会真的执行工具，评分器再检查工作区。同一套题再跑一次，各题分数不变。

回放一条轨迹。这一步只读日志，不会再次调用智能体：

```bash
aeo replay demo --task fix-sum
```

工具过程如下。完整命令还会为每条评分打印一行 `[grade]`。不开启评判模型时，`llm_judge` 显示为 `SKIP`，该题分数仍是 1.00：

```text
[step 1 tool_call] read_file {"path": "math_utils.py"}
[step 1 observation] read_file ok
math_utils.py  lines 1-2 of 2
   1| def add(a, b):
   2|     return a - b

[step 2 tool_call] edit_file {"new": "return a + b", "old": "return a - b", "path": "math_utils.py"}
[step 2 observation] edit_file ok
updated math_utils.py (1 replacement)

[final]
add() now returns the sum of its arguments.

[task_end] PASS score=1.00

# replay complete (events printed from the log; the agent was not re-run)
```

对比两次已经保存的运行。仓库里放了一对示例，不必先自己跑出两份结果：

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

`fizzbuzz` 和 `search-todo` 变好了，`edit-json` 退步了。分类表把题目汇总起来：`coding` 从 3/4（平均 0.88）到 4/4（平均 1.00），`tool-use` 仍是 3/4、平均 0.75。一类的合计可以不变，总通过率也可以从 6/8 升到 7/8，同时这一类里仍有题目退步。加上 `--fail-on-regression` 后，只要有共享任务的分数下降，进程就以 1 退出。`aeo compare --format json` 把同一次对比打成一个 JSON 对象。

汇总一次已经落盘的运行。这一步读取 `summary.json` 和各题的 `trajectory.jsonl`，不会调用适配器：

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

这份示例里只有 `fix-sum` 有轨迹：一次成功的 `edit_file` 改了 `math_utils.py`，并且有 `final` 事件。其余各行来自 summary，没有工具计数，`final` 为 `no`。`--task fix-sum` 只留一行。`--format json` 把同样的汇总打成一个 JSON 对象。

列出一次已经落盘的运行里没有通过的题目。这一步只读保存的结果，不调用适配器，也不再给工作区打分：

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

baseline 里失败的是 `fizzbuzz`（0.50）和 `search-todo`（0.00），顺序与 summary 一致。0.50 这种部分分数仍然算失败。candidate 里唯一的失败是 `edit-json`，分数 0.00。这两份示例的 `grades` 都是空数组，也没有 `result.json`，所以评分列和 detail 是 `-`，命令不会编造评分器 id 或原因。

评分按这个顺序取第一个非空列表：任务在 `summary.json` 里的 `grades`，然后是 `tasks/<id>/result.json`，最后是轨迹里 `kind` 为 `grade` 的事件。一次真实的 `aeo run` 会把评分写进这三处。失败评分的 id、type 和保存下来的 `detail` 会在有记录时出现。跳过的评分（例如没开的可选 `llm_judge`）写在 `skipped` 列，不算失败。任务上非空的 `error` 会进 detail。`--task fizzbuzz` 只留一行。如果这道题通过了，命令打印 `no failures`，退出码仍是 0。`--format json` 把同一份清单打成一个 JSON 对象。退出码 0 表示报告本身成功，即使清单不是空的。

列出一次已经落盘的运行里每一道题的评分，包括通过的题。通过、失败、跳过的评分分列。这一步只读保存的结果，不调用适配器，也不再给工作区打分：

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

baseline 的 8 道题都会出现，顺序与 summary 一致。6 道通过，2 道失败。评分来源与 `aeo failures` 相同，空数组不算。这两份示例的 `grades` 都是空数组，也没有 `result.json`。candidate 没有轨迹，所以评分列全是 `-`。baseline 里另外 7 道题也没有保存下来的 `grade` 事件，那些列同样是 `-`。这个 `-` 是记录里本来就没有，不是命令猜的。`fix-sum` 是这份示例里的例外：轨迹中有一条已经通过的 `grade` 事件，`tests:pytest`，通过列因此显示这个 id。`aeo failures` 不列出这一行，因为这道题通过了。一次真实的 `aeo run` 会把评分写进 summary、`result.json` 和轨迹。这条命令只读这些文件，不会重新跑智能体。

`passed` 为真且没有跳过，算通过；`skipped` 为真，算跳过；其余 `passed` 不为真的算失败。单元格按首次出现写成 `id:type`，空列表写成 `-`。失败评分的 id 和 type 在表下的 `graders` 行合并计数，方式和 `aeo failures` 一样；没有失败评分时不打印这一行。`--task fix-sum` 只留一行，题通过了也会留下。`--format json` 把同一份清单打成一个 JSON 对象。退出码 0 表示报告本身成功，即使每道题都失败，或者每条评分列表都是空的。

按题目文件列出这套题的覆盖情况。这一步不运行适配器，不评分，也不写运行目录：

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

行序就是文件名顺序。`graders` 按声明顺序列出类型。同一题里重复的类型会合并（`contains×2`）。可选评分带 `?`（`fix-sum` 的 `llm_judge?`）。同一类型既有必过又有可选时，两种次数都保留，例如 `contains×2 (1 optional)`。没有工具时 `tools` 是 `-`。`mock` 是 mock 步数，`files` 是初始文件数。表下面汇总题数、按首次出现排列的类别、各评分器类型的条目数、至少有一步 mock 的题，以及 `required: false` 的评分。`--format json` 把同一份清单打成一个 JSON 对象，后面没有别的输出：`version`、`suite`、`tasks`（`id`、`category`、含 `id` / `type` / `required` 的 `graders`、`tools`、`mock`、`files`），以及汇总字段 `task_count`、`categories`、`grader_types`、`with_mock`、`optional_graders`。`--fail-on-incomplete` 在任一已加载题目没有 mock 步时退出码为 1，因为离线 CI 的适配器依赖这些脚本。每道题都有 mock 时退出码仍是 0。可选评分不算未完成。套件缺失、为空或无法通过校验时退出码为 2。

生成一份自包含的 HTML 报告，或把 Markdown 打到标准输出：

```bash
aeo report demo --format html --out report.html
aeo report demo --format md
aeo list-runs
```

## 一次运行留下什么

每次运行写入 `.aeo/runs/<run_id>/`：

```text
manifest.json
summary.json
scoreboard.txt
tasks/<task-id>/trajectory.jsonl
tasks/<task-id>/result.json
tasks/<task-id>/workspace/    # 智能体停下时的文件
```

全部必过评分通过时 `aeo run` 退出码为 0，任一必过评分失败时为 1。退出码 2 表示参数、套件或运行编号有问题。

单题分数是「实际执行了的评分器」的加权平均。可选的 LLM 评判默认跳过，跳过的评分不进入分母，因此离线的 `8/8` 不依赖网络。通过率统计必过评分全部通过的题目。平均分是各题分数的算术平均。

## 结构

```text
suites/*.yaml                 题目：提示、初始文件、评分器、mock 脚本
        │
        ├── src/aeo/inventory  从题目文件列覆盖；不调用适配器，不写运行
        ▼
src/aeo/runner                准备隔离工作区，循环到最终回答
        │
        ├── src/aeo/adapters  mock | openai | command
        ├── 工具运行时         read、write、edit、list、search
        └── JSONL 记录
        │
        ▼
src/aeo/graders               精确匹配、包含、正则、pytest、JSON、工具使用、评判模型
        │
        ▼
.aeo/runs/<run_id>/
        │
        ├── src/aeo/replay    打印轨迹
        ├── src/aeo/stats     从 JSONL 汇总工具次数
        ├── src/aeo/failures  从已保存的运行列出失败题目和评分
        ├── src/aeo/grades    每一题通过、失败、跳过的评分
        ├── src/aeo/compare   逐题差值、分类汇总和通过率
        └── aeo report        HTML 或 Markdown
```

工具由运行器执行。循环内的适配器只提出下一步动作。路径会解析到该题工作区之内；指向外部的符号链接或 `..` 会变成一次失败的观察。`no_path_escape` 可以把「试图越界」本身判为失败。

## 命令

```text
aeo run --suite suites --adapter mock --run-id demo
aeo run --task fix-sum --task fizzbuzz
aeo replay demo --task fix-sum --format text
aeo stats RUN --task fix-sum --format text
aeo failures RUN --task TASK_ID --format text   # 或 json
aeo grades RUN --task TASK_ID --format text     # 或 json；包括通过的题
aeo compare RUN_A RUN_B --format text --fail-on-regression    # 或 json
aeo list-runs --root .aeo/runs
aeo list-tasks --suite suites --format text     # 或 json；--fail-on-incomplete
aeo report demo --format html --out report.html
```

`RUN` 可以是 `--root`（默认 `.aeo/runs`）下的运行编号，也可以是含有 `summary.json` 的目录。`list-tasks` 不接收运行编号。它读 `--suite`（默认 `suites`），不写 `.aeo/runs`。

## 题目

`suites/` 里有 8 道题，按文件名顺序执行。

| 题目 | 类别 | 要求 |
| --- | --- | --- |
| `fix-sum` | coding | 把 `add()` 从减法改成加法，并由 pytest 检查。 |
| `fizzbuzz` | coding | 实现 `fizzbuzz(n)`。 |
| `parse-ints` | coding | 跳过 `int()` 无法解析的片段。 |
| `add-docstring` | coding | 补上一行同时提到 greeting 和 name 的文档字符串。 |
| `read-config` | tool-use | 读 JSON 配置，回答端口 4815。 |
| `search-todo` | tool-use | 搜索 TODO，只回答相对路径。 |
| `edit-json` | tool-use | 把 `debug` 改为 false，其余字段保持不变。 |
| `safe-refusal` | tool-use | 拒绝写入 `/tmp/...` 和 `../escape.txt`。 |

每个文件是一道题：`prompt`、初始 `files`、允许的 `tools`、`graders`，以及一段 `mock` 脚本。Mock 脚本就是离线智能体，写在数据里，CI 里的分数因此固定。

## 评分器

| 类型 | 检查什么 |
| --- | --- |
| `exact` | 文件或最终回答与 `value` 完全相同。 |
| `contains` | 文件或最终回答包含子串。 |
| `regex` | 对文件或最终回答做正则匹配。 |
| `pytest` | 在任务工作区里运行 pytest，退出码 0 为通过。 |
| `json_subset` | JSON 文件包含 `expect` 对象。 |
| `tool_used` | 指定工具至少被调用 `min_count` 次。 |
| `tool_any` | `tools` 里至少有一个被调用。 |
| `tool_absent` | 指定工具没有被调用。 |
| `file_absent` | 运行结束后相对路径不存在。 |
| `no_path_escape` | 工具参数没有解析到工作区之外。 |
| `llm_judge` | 可选，模型给出 `[0, 1]` 的分数。未开启时跳过。 |

`target` 取 `file` 或 `answer`。`required: false` 的评分可以拉低分数，同时题目仍然记为通过。`fix-sum` 的评判模型用的就是这种方式。

开启评判模型：

```bash
export OPENAI_API_KEY="sk-..."
export AEO_LLM_JUDGE=1
aeo run --adapter openai --llm-judge
```

`OPENAI_BASE_URL` 和 `OPENAI_MODEL` 可选。`--config examples/config.example.toml` 可以写 `model` 和 `base_url`。配置文件里的密钥会被忽略。轨迹记录模型名和工具过程，不记录 API key。

## 适配器

| 适配器 | 作用 |
| --- | --- |
| `mock` | 回放每道题的 `mock:` 脚本。结果确定，CI 使用这一档。 |
| `openai` | 向兼容 OpenAI 的 `{base_url}/chat/completions` 发请求，并使用内置工具。 |
| `command` | 启动外部程序。提示从标准输入送入。`{workspace}`、`{task_id}`、`{prompt}` 会替换进参数。不经过 shell。 |

`MockAgentAdapter` 和 `OpenAICompatibleAgentAdapter` 实现 `step()`。运行器执行工具并写回观察。`CommandAgentAdapter` 自己掌握整段循环：外部程序直接改工作区。

### 和编程智能体的关系

这个仓库评测智能体。一个本地编程智能体负责改工作区；如果它考虑审计，还会自己写会话日志。[dm-code-agent](https://github.com/KDB1223/dm-code-agent) 就是这样的智能体：ReAct 循环、工作区工具、追加写入的 JSONL 会话。本机已经安装它时，可以用命令适配器接进来：

```bash
aeo run --adapter command \
  --command python --command -m --command dm_agent \
  --command run --command - \
  --command --workspace --command {workspace} \
  --ingest-glob '.dm-agent/sessions/*.jsonl'
```

`run -` 从标准输入读题目。`--ingest-glob` 把对方的 JSONL 抄进 aeo 轨迹，记为 `external` 事件。对方的日志格式保持原样，这里仍然有一份可以回放的文件。演示本身不克隆、也不导入 dm-code-agent。`aeo run --adapter mock` 就是完整的离线路径。

任何「读提示、改当前工作区、把最终回答打到标准输出」的本地程序都可以用同一形状接上。说明和一小段 `BaseAgentAdapter` 示例在 [examples/external_agent.md](examples/external_agent.md)。

循环内适配器会记下本运行器执行的每一次工具调用。命令适配器记下进程边界，以及你指定导入的 JSONL。两种运行都会留下 `aeo compare` 能对比的目录。改提示或换模型之后，差异会落在记分板上。

## 轨迹

`trajectory.jsonl` 的每一行是一个 JSON 对象。`kind` 可以是：

`task_start`、`prompt`、`thought`、`tool_call`、`observation`、`final`、`grade`、`task_end`、`error`、`external_start`、`external`。

一次 `tool_call` 和对应的 `observation` 共用 `step` 与 `call_id`。`grade` 行与 `summary.json` 里的评分对象相同。`replay` 和 `stats` 只读这个文件。`stats` 统计工具调用，以及成功的 `edit_file` / `write_file` 路径。`failures` 和 `grades` 只有在该题的 `summary.json` 和 `result.json` 都没有非空 `grades` 时，才使用这里的 `grade` 事件。`grades` 会留下每一道题，包括通过的题。这些命令都不会调用智能体。

## 开发

```bash
python -m pip install -e ".[dev]"
pytest
aeo list-tasks --suite suites --fail-on-incomplete
aeo run --adapter mock --run-id ci-mock
aeo compare examples/fixtures/runs/baseline examples/fixtures/runs/candidate
aeo stats examples/fixtures/runs/baseline
aeo failures examples/fixtures/runs/baseline
aeo grades examples/fixtures/runs/baseline
```

需要 Python 3.11 及以上。运行时依赖 PyYAML。pytest 是开发额外依赖，pytest 评分器使用当前解释器。CI 在 3.11 和 3.12 上运行测试、对自带套件执行 `aeo list-tasks`，以及 mock 记分板。

见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 目录

```text
suites/                         八道题
src/aeo/adapters/               BaseAgentAdapter、mock、OpenAI 兼容、command
src/aeo/runner/                 工作区隔离、工具、JSONL 运行目录
src/aeo/graders/                规则评分和可选评判模型
src/aeo/replay/                 渲染轨迹
src/aeo/stats.py                已保存运行的工具用量汇总
src/aeo/failures.py             已保存运行的失败题目和评分
src/aeo/grades.py               每一题通过、失败、跳过的评分
src/aeo/inventory.py            从题目文件列出覆盖清单
src/aeo/compare/                记分板差值
src/aeo/cli.py                  aeo run | replay | compare | list-runs | list-tasks | report | stats | failures | grades
examples/fixtures/runs/         用于 compare 的 baseline 与 candidate
examples/external_agent.md      如何接上本地编程智能体
examples/config.example.toml    模型与 base URL，不含密钥
docs/lab-zh.md                  课程实验
```

## 许可证

[MIT](LICENSE)。Copyright 2026 agent-eval-obs contributors.
