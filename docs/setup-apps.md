# Setting up apps

Every app connects to the same Roundtable server: `<python> -m roundtable_ai mcp`, with `RT_HOME` pointing at your project's `.roundtable` folder. `rt setup` writes that entry for you. It always merges with your existing settings, saves a timestamped backup first, refuses to touch a file it can't parse, and shows the change without writing it if you add `--dry-run`. `--remove` takes the entry out again.

The entry uses the full path of the Python that Roundtable is installed in, so apps don't depend on your shell's PATH. If you reinstall Python or Roundtable somewhere else, run `rt setup` again (`rt doctor` tells you when an entry is stale).

## Claude Code (terminal or VS Code)

The simplest way is to let Roundtable start each seat:

```bash
rt seat add opus --model claude-opus-5-5 --app claude-code
rt launch opus
```

`rt launch` runs `claude` in the seat's working copy with `--model`, an MCP config file bound to that seat (`.roundtable/seats/opus/mcp.json`) and a first message telling it to call `rt_sync`. Use `rt launch opus --print` to see the exact command.

To use Roundtable from Claude Code sessions you start yourself (including the VS Code extension):

```bash
rt setup claude-code     # writes .mcp.json in the project folder
```

Claude Code asks you to approve project MCP servers the first time; allow `roundtable`. Then tell the session: "join Roundtable as opus".

## Claude desktop app

```bash
rt setup claude-app
```

This adds an entry named `roundtable-<project>` to `claude_desktop_config.json`:

| System | File |
| --- | --- |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

Restart the app, start a chat and say "join Roundtable as fable". Several projects can coexist: each has its own entry name.

## Codex CLI, Codex VS Code extension, ChatGPT desktop app (Codex mode)

All three read `~/.codex/config.toml` (or `$CODEX_HOME/config.toml`), so one command covers them:

```bash
rt setup codex
```

It adds a `[mcp_servers.roundtable-<project>]` table with `tool_timeout_sec = 120` and leaves every other line of the file, including comments, untouched. Verified with Codex CLI 0.162.1.

- **Codex CLI:** `rt launch sol` starts `codex` in the seat's working copy, with the model and the seat binding passed as `-c` overrides.
- **ChatGPT desktop app:** switch to Codex mode, open the seat's working copy folder (`rt seat list` shows it), and say "join Roundtable as sol56".
- **VS Code extension:** open the seat's working copy folder and say the same.

## Other MCP apps

Any app that can start a local (stdio) MCP server works. Configure:

- command: the Python Roundtable is installed in (`rt doctor` prints it)
- arguments: `-m roundtable_ai mcp`
- environment: `RT_HOME=/path/to/project/.roundtable` (and `RT_SEAT=<seat>` if that app only ever hosts one seat)

Register the seat with `--app other`.

## ChatGPT Chat mode

Not supported in v0.1. Chat mode reaches custom MCP servers only through Developer Mode and a public HTTPS tunnel, which conflicts with Roundtable's local-only design.
