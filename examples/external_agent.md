# Plug an external coding agent into agent-eval-obs

The demo does not need another repository. `aeo run --adapter mock` replays the
`mock:` scripts in `suites/` and grades the workspace those scripts produce.

A real agent is a second process. `agent-eval-obs` prepares a fresh workspace
for each task, starts the process with the task prompt on stdin, then grades
the files left behind. Tool calls that happen inside that process are not
visible unless you point `--ingest-glob` at a JSONL log the agent already writes.

## Command adapter

`{workspace}`, `{task_id}`, and `{prompt}` are replaced in each argument.
Arguments are passed as a list. There is no shell.

```bash
aeo run --adapter command \
  --command python --command -m --command dm_agent \
  --command run --command - \
  --command --workspace --command {workspace} \
  --ingest-glob '.dm-agent/sessions/*.jsonl'
```

That command is the shape of the local coding agent at
<https://github.com/KDB1223/dm-code-agent>: `run -` reads the task from stdin,
`--workspace` selects the directory, and each session is an append-only JSONL
file. This harness does not import that project and does not ship its code.
Install it yourself when you want to grade it. Until then, use `--adapter mock`.

The same adapter can wrap any other local program that edits the current
directory and prints a final answer on stdout:

```bash
aeo run --adapter command \
  --suite suites \
  --command python --command my_agent.py --command --root --command {workspace}
```

`my_agent.py` should read the prompt from stdin. Exit 0 when the agent
finishes. The score still comes from the graders, which look at the workspace
and at that stdout.

## In-loop adapter

Subclass `BaseAgentAdapter` when you want every tool call in the aeo
trajectory. Implement `begin` and `step`. Return `AgentAction(kind="tool", ...)`
or `AgentAction(kind="final", content=...)`. The runner executes `read_file`,
`write_file`, `edit_file`, `list_dir`, and `search` inside the task workspace
and refuses paths that leave it.

```python
from aeo.adapters.base import BaseAgentAdapter
from aeo.models import AgentAction, AgentState


class EchoAdapter(BaseAgentAdapter):
    name = "echo"

    def step(self, state: AgentState) -> AgentAction:
        return AgentAction(kind="final", content="I refuse to leave the workspace.")
```

Pass an instance to `aeo.runner.execute.run_suite`. The OpenAI-compatible
adapter (`--adapter openai`) is the built-in example of this style: it posts
to `{base_url}/chat/completions` and turns tool calls into the runner's tools.
The API key stays in `OPENAI_API_KEY` and is not written to the run directory.

## What gets graded

Graders run after the agent stops. They can read files, run pytest in the
task workspace, and scan the trajectory for tool names. A command adapter
records the process boundary (`external_start`, stdout, and any ingested
JSONL lines). An in-loop adapter records every thought, tool call, and
observation. Both produce a run directory that `aeo compare` can diff.
