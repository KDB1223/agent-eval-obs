# 实验：给编程智能体做可回放的评测

课程里的智能体实验常常停在「它好像改对了」。这一次换成另一件事：把一次运行变成可以复查的记录，并且让第二次运行能和第一次比。

工具是本仓库的 `agent-eval-obs`。它不代替智能体写代码。它准备题目、调用适配器、把轨迹落成 JSONL，再用规则给结果打分。

## 实验目标

做完后你应该能指出三样东西：

1. 一份不依赖网络、重复运行分数不变的记分板。
2. 某一题轨迹里，用户提示、一次工具调用、以及紧跟着的观察，三者如何对应。
3. 两次运行之间，哪一题变好了，哪一题退步了。通过率上升并不能代替这张逐题表。

## 和 dm-code-agent 的关系

[dm-code-agent](https://github.com/KDB1223/dm-code-agent) 是一个本地编程智能体：它在一个工作区里按 ReAct 循环调用工具，并把会话追加写入 JSONL。本实验的对象是评测台。评测台站在智能体外面，负责出题、收结果、打分、对比。

两者可以接在一起，但本实验的演示不需要克隆那个仓库。离线路径使用 Mock 适配器：每道题的 YAML 里有一段 `mock:` 脚本，运行器按脚本发出工具调用，再真的在隔离目录里执行这些工具。脚本是数据，所以分数可复现。

若本机已经装有 dm-code-agent，可以用命令适配器把它当作被测程序。接法写在 [examples/external_agent.md](../examples/external_agent.md)。那个适配器不导入对方的源码，只启动进程，并可选地把对方的 JSONL 抄进本次轨迹。

## 准备

```bash
git clone https://github.com/KDB1223/agent-eval-obs.git
cd agent-eval-obs
python -m pip install -e ".[dev]"
pytest
aeo run --adapter mock --run-id lab
```

`pytest` 应该通过。记分板应为 `8/8`，平均分 `1.00`。运行目录在 `.aeo/runs/lab/`。这个目录是本地输出，不要提交。

## 步骤

### 1. 读记分板，再打开一条轨迹

```bash
aeo replay lab --task fix-sum
```

在输出里找到这三行，并在实验报告里按顺序引用它们（时间戳会变，事件种类不变）：

- `[prompt]` 下面的题目原文
- `[step 1 tool_call] read_file`
- 紧接着的 `[step 1 observation]`

观察文本来自运行器实际读到的文件，不是脚本里预先写好的一段「假装的工具结果」。可以打开 `.aeo/runs/lab/tasks/fix-sum/workspace/math_utils.py`，核对它已经变成加法。

再看 `safe-refusal`。这道题的正确行为是拒绝。轨迹里不应出现 `write_file`。评分器 `no_path_escape` 会把越界路径参数判为失败，即使用工具运行时已经拦住了写入。

### 2. 对比两次运行

仓库里有一对现成结果，用来练习回归表，不必改模型：

```bash
aeo compare examples/fixtures/runs/baseline examples/fixtures/runs/candidate
```

记录这三行的含义：

- `improvements` 里的题目
- `regressions` 里的题目
- `pass rate` 和 `mean score` 各自怎么变

候选运行的通过率更高，同时 `edit-json` 从通过变成失败。实验报告需要单独写出这道退步的题，不能只用「7/8 比 6/8 更好」收尾。

加上 `--fail-on-regression` 再跑一次，确认进程退出码是 1。这是 CI 里用来卡住退步的开关。

### 3. 改一道题，让分数动起来

复制 `suites/06-search-todo.yaml` 的思路即可，改动要小。例如把 `search-todo` 的 mock 最终回答从 `src/b.py` 改成 `src/a.py`，然后：

```bash
aeo run --adapter mock --run-id lab-bad --task search-todo
aeo compare lab lab-bad --root .aeo/runs
```

`search-todo` 的精确匹配评分应该失败，差值表里出现退步。做完把 YAML 改回去，再跑一次 `--run-id lab-ok`，确认这道题回到通过。报告里贴出改动前后的两行差值即可。

也可以新增一道自己的题：在 `suites/` 里加一个 YAML，给出初始文件、至少一条规则评分，以及一段能稳定通过的 `mock`。文件名顺序就是运行顺序。

### 4. 可选：打开评判模型

规则评分看得到文件和工具名。它看不出解释是否清楚。`fix-sum` 里有一条 `required: false` 的 `llm_judge`。默认跳过，所以离线分数不变。

```bash
export OPENAI_API_KEY="sk-..."
export AEO_LLM_JUDGE=1
aeo run --adapter mock --llm-judge --run-id lab-judge --task fix-sum
aeo replay lab-judge --task fix-sum
```

在轨迹里找到 `judge` 那一行。它不再是 `SKIP`。因为这条评分不是必过项，题目可以仍然显示 PASS，同时分数低于 1。报告里写清楚：通过率回答「必过规则是否都过了」，平均分才会吃进这条可选评分。

没有密钥时跳过这一步。不要把密钥写进仓库或轨迹。

## 思考题

1. Mock 脚本保证了分数可复现。它没有保证一个真实模型会这么做。如果把适配器换成 `openai` 或 `command`，哪一部分记录仍然可比，哪一部分会变？
2. `safe-refusal` 同时检查了「最终回答里有拒绝」和「没有调用写入工具」。只保留其中一条，会漏掉什么行为？
3. 命令适配器导入的 `external` 事件保留了对方日志的原样 JSON。这样做的好处是什么？如果评测台改写对方的字段，回放时会失去什么？
4. 为什么越界路径要在工具运行时拒绝一次，再在评分器里记一次？两次的读者分别是谁？

## 报告里建议出现的材料

- `aeo run --adapter mock` 的记分板。
- `fix-sum` 轨迹中一次工具调用和它的观察。
- `baseline` 与 `candidate` 的差值表，并点名退步的题目。
- 你对思考题 1 和 4 的回答，各用几句话即可。

评分看这四样是否具体，不看形容词。
