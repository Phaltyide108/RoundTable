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

**In VS Code:** add the seat with `--app claude-vscode`. Roundtable writes a `.mcp.json` bound to that seat into the seat's working copy (hidden from git through `.git/info/exclude`). The dashboard's **Start** opens that folder in VS Code; in the Claude Code panel, allow the `roundtable` server when asked and send "check roundtable".

To use Roundtable from Claude Code sessions you start yourself in the project folder:

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
- **Commits from Codex:** Codex's sandbox keeps `.git` read-only (checked with Codex CLI 0.162.1), so a plain `git commit` needs your approval each time. Seats are told they can pass `commit=true` to `rt_task checkpoint` or `rt_task close` instead: Roundtable then commits only the files leased to that seat, with the seat as the commit author.
- **ChatGPT desktop app:** switch to Codex mode, open the seat's working copy folder (`rt seat list` shows it), and say "join Roundtable as sol56".
- **VS Code extension:** add the seat with `--app codex-vscode`; the dashboard's **Start** opens its working copy in VS Code. Send "join Roundtable as sol" in the Codex panel.

## Gemini CLI, Qwen Code, opencode, Cursor

Add the seat with `--app gemini-cli`, `qwen-code`, `opencode` or `cursor`. Roundtable writes that app's project settings file, bound to the seat, into the seat's working copy and hides it from git:

| App | File in the working copy | Format |
| --- | --- | --- |
| Gemini CLI | `.gemini/settings.json` | `mcpServers.roundtable` with `command`, `args`, `env`, `timeout`, `trust: false` |
| Qwen Code | `.qwen/settings.json` | same as Gemini CLI |
| opencode | `opencode.json` | `mcp.roundtable` with `type: "local"`, `command` (array), `environment` |
| Cursor | `.cursor/mcp.json` | `mcpServers.roundtable` with `type: "stdio"`, `command`, `args`, `env` |

`rt launch gem` (or **Start**) opens the app in that folder; send "check roundtable" once it is ready. Cursor is opened with its `cursor` command. The model is chosen inside the app; the model name you give Roundtable is used for display and to tell companies apart.

## GitHub Copilot CLI

```bash
rt setup copilot        # adds Roundtable to ~/.copilot/mcp-config.json (type local, tools ["*"])
rt seat add cop --model gpt-6.1-sol --app copilot-cli
rt launch cop           # starts copilot in the seat's working copy
```

Send "join Roundtable as cop" when it is ready.

## Other MCP apps

Any app that can start a local (stdio) MCP server works. Configure:

- command: the Python Roundtable is installed in (`rt doctor` prints it)
- arguments: `-m roundtable_ai mcp`
- environment: `RT_HOME=/path/to/project/.roundtable` (and `RT_SEAT=<seat>` if that app only ever hosts one seat)

Register the seat with `--app other`.

## ChatGPT Chat mode

Not supported. Chat mode reaches custom MCP servers only through Developer Mode and a public HTTPS tunnel, which conflicts with Roundtable's local-only design.
