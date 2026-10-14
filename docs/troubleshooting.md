# Troubleshooting

Start with `rt doctor`. It checks Python, the project, git, every seat's working copy, the commit guard, each app's settings, stale proofs and frozen state, and prints the fix for each problem.

| Symptom | Cause | Fix |
| --- | --- | --- |
| `rt: command not found` | pipx/uv put it in a folder not yet on PATH | open a new terminal, or run `pipx ensurepath` |
| "this folder is not inside a Roundtable project" | run from outside the project, or `rt init` not done | `cd` into the project, or `rt init` |
| "no Roundtable database at ..." from an app | `RT_HOME` in the app settings points at an old location | `rt setup <app>` again |
| Claude Code shows `roundtable` as pending | project servers need approval once | run `claude` in the project and allow it |
| "seat X is live in another chat" | the seat's previous chat is still marked active | if that chat is closed: `rt seat release X` |
| "this chat has not joined a seat yet" | a new chat in a desktop app | say "join Roundtable as X" |
| "you have N unread update(s) meant for you" | the seat must read news before claiming | the model calls `rt_sync` |
| "STOP: ..." | a level-5 alert, or you ran `rt freeze` | `rt alert list` and resolve it, or `rt unfreeze` |
| A task "waits to merge" | your main folder has uncommitted changes, is on another branch, or there is a conflict | `rt status` shows why; fix it, then `rt task merge` |
| "git does not know your name and email yet" | git identity not configured | `git config --global user.name "Your Name"` and `git config --global user.email you@example.com` |
| Codex says `git commit` failed: "Read-only file system" on `.git/.../index.lock` | Codex's sandbox (workspace-write) keeps every `.git` folder read-only | approve running it outside the sandbox when Codex asks, or have the seat pass `commit=true` to `rt_task checkpoint`/`close` so Roundtable commits its leased files |
| Commit stopped by "roundtable: commit stopped" | a seat tried to commit files it doesn't lease | unstage them, or lease them first (`rt_lease extend`) |
| A proof keeps timing out | slow tests | `rt config set proof.timeout_seconds 1800` |
| Background wake-ups don't happen | the seat runs in a desktop app, or `claude`/`codex` isn't on PATH | desktop apps can't be woken: answer the notification yourself; for CLI seats, see `rt doctor` |
| `rt app` opens a browser tab, not a window | no window toolkit found | Linux: install `python3-gi` and `gir1.2-webkit2-4.1` (or WebKit 6), or Chrome/Chromium/Brave/Edge; `rt doctor` says what it found |
| Roundtable isn't in the app menu | the menu entry was never added | `rt app --install` (remove it with `rt app --uninstall`) |
| Started from the menu, an AI "is not installed" | the menu didn't pass your terminal's PATH and the login shell didn't add it either | run `rt doctor` from a terminal; make sure `claude`/`codex`/`opencode` are on the PATH your login shell sets (`~/.profile`) |
| "Ask the table": an AI "couldn't" answer | not signed in, or the app's own limit | the reason is shown on its card; sign in once with `claude`, `codex` or `opencode` in a terminal |
| No desktop notifications on Linux | `notify-send` not installed | install `libnotify-bin` (Debian/Ubuntu); notifications are also written to `.roundtable/logs/notifications.log` |

## Logs

- `.roundtable/logs/mcp.log`: what each app asked the server
- `.roundtable/logs/errors.log`: unexpected errors, with details (please attach to bug reports)
- `.roundtable/logs/watch.log`, `notifications.log`, `wake-<seat>.log`
- `.roundtable/proofs/<run>.log`: the background proof runner
- `.roundtable/logs/run-<seat>.log`, `runner-<seat>.log`: background runs; `council-<id>.log`: a question to the table
- `~/.config/roundtable/app.log`: the app window when started from a terminal
- `rt log`: the project's full event history

## Starting over

Everything Roundtable keeps for a project is in `.roundtable/`. To start fresh, move that folder aside and run `rt init` again. Seat working copies (`../project.<seat>`) can be removed with `git worktree remove <path>`.
