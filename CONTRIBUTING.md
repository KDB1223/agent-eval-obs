# Contributing

Thanks for looking at agent-eval-obs. Small, focused changes are the most useful ones.

## Setup

```bash
python -m pip install -e ".[dev]"
pytest
aeo run --adapter mock
```

`pytest` and the mock suite must pass with no API key and no network.

## Adding a task

Add one YAML file under `suites/`. Filename order is run order. Give the task
an id, a prompt, starter `files`, the `tools` it may call, at least one grader,
and a `mock:` script so `aeo run --adapter mock` stays deterministic. Re-run
the mock suite and update the README scoreboard if the pass line changes.

## Adding an adapter

Subclass `BaseAgentAdapter` in `src/aeo/adapters/`.

- In-loop agents implement `step` and let the runner execute tools.
- External programs set `owns_loop = True` and implement `run_task`.

Keep secrets out of the trajectory. The OpenAI adapter reads `OPENAI_API_KEY`
and records only the model name.

## Runs

Directories under `.aeo/` are local output. Do not commit them. Checked-in
comparisons belong in `examples/fixtures/runs/`.

## License

By contributing you agree that your changes are released under the MIT license
in `LICENSE`.
