# Contributing

Thanks for helping. Roundtable aims to be boring to install and impossible to misread, so changes are judged on reliability and clarity first.

## Development setup

```bash
git clone https://github.com/OWNER/roundtable
cd roundtable
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev,mcp-tests]"
git config --global user.name >/dev/null || git config --global user.name "You"
python -m pytest
```

The `mcp-tests` extra installs the official MCP client so the end-to-end protocol test runs; without it that one test is skipped.

## Ground rules

- **No new runtime dependencies.** Roundtable uses only the Python standard library (plus `tomli` on Python 3.10). This keeps installs from breaking.
- **Python 3.10+ syntax.** CI runs 3.10 to 3.13 on Linux, macOS and Windows.
- **Every expected failure is an `RTError(code, message, hint)`**, where the hint is the exact next step. Never let a user or a model see a raw traceback for something we could foresee.
- **Every state change happens in `with ctx.tx():` and emits exactly one event.** Digests, the dashboard and exports are built from events.
- **Replies stay short.** Models read every reply; compact lines save their context.
- **Never touch the user's uncommitted work**, and never overwrite a config file without merging and backing it up.

## Adding an operation

Operations are plain functions registered with `@op` in `registry.py`. The MCP server and the CLI pick them up automatically.

```python
from .registry import Param, Result, op

@op("task.example", tool="rt_task", action="example", desc="One line for the tool description",
    params=[Param("task", required=True)])
def example(ctx, task) -> Result:
    with ctx.tx():
        ...
        events.emit(ctx, "task.example", f"{ctx.actor} did something to {task}", task=task)
    return Result("short answer", {"task": task})
```

Use `who=HUMAN` for operations only the human may run (no `tool`), and `frozen_ok=True` for read-only actions that must still work during a STOP. Then run `python scripts/gen_docs.py` to refresh `docs/cli.md` and `docs/mcp-tools.md`, and add tests.

## Tests

Use the fixtures in `tests/conftest.py` (`rt`, `rt_nogit`, `repo`). Tests must not need network access, accounts or the real apps. Set `RT_PROOF_INLINE=1` (see `tests/test_flow_end_to_end.py`) to run proofs in-process.

## Pull requests

Describe the user-visible change, link an issue if there is one, and include tests. Keep the CHANGELOG updated.
