# Edge cases and failure handling

Every failure has a defined outcome and a message that says what to do next. Most of these are covered by the test suite.

| Situation | What Roundtable does |
| --- | --- |
| Two seats claim the same task at the same moment | The claim runs in a locked database transaction; exactly one wins and the other is told who has it (tested with 4 processes) |
| A claim succeeds in the database but the git branch switch fails | The claim is undone; nothing is left half-done |
| A seat's chat crashes while holding files | Its leases expire after 30 minutes without activity; the digest says the files are free again |
| A second chat tries to take a seat that is already live | Refused, with the fix: `rt seat release <seat>` if the other chat is closed |
| A desktop app shares one connection across several chats | Every call carries the chat's seat key, so chats never act as each other |
| A model forgets to sync | Claiming is refused while it has unread updates meant for it |
| A model runs `rt` commands from its own working copy | They act as that seat; human-only commands are refused |
| Database busy (several seats writing at once) | Waits up to 10 seconds, then "busy, try again" |
| Project in Dropbox, OneDrive, iCloud or Google Drive | `rt doctor` warns: syncing can corrupt the database |
| A proof takes longer than the app allows a tool call (Codex: about 60 s) | Proofs run in a separate background process; close answers "running" and the result arrives in the digest |
| A proof hangs or prints megabytes | Stopped at its time limit (the whole process tree); only the last 40 lines are kept |
| The proof runner is killed (reboot, crash) | Detected and marked as an error; the task goes back to its owner |
| Proofs leave `__pycache__` or similar behind | Ignored when checking for uncommitted work |
| Uncommitted changes when closing a task | Close refused, listing the files; the proof checks exactly what gets merged |
| Committed changes to files the seat doesn't lease | The commit guard stops the commit; if bypassed (`--no-verify`), close is refused |
| Merge conflict with other work | The task waits as "merge blocked" and its owner gets a level-3 alert; the merge is aborted cleanly |
| You have uncommitted changes in your main folder | Merges wait; your files are never touched; `rt task merge` (or `rt watch`) retries |
| Your main folder is on another branch | Merges wait, with the fix (`git switch main`) |
| git doesn't know your name/email | Clear message with the exact `git config` commands |
| Project is not a git repository | Shared-folder mode: leases still enforced, no working copies or diffs; reviews see file lists |
| Repository has no commits yet | Working copies refused, with "make a first commit" |
| `rt init` in a subfolder or in a seat's working copy | Refused, pointing at the right folder |
| A folder already exists where a working copy should go | Refused; never overwritten; choose another location with `rt config set git.worktree_dir` |
| A working copy was deleted by hand | `rt doctor` notices; `rt seat worktree <seat>` repairs it |
| An existing git pre-commit hook (or husky) | Never overwritten: Roundtable chains to it, or prints the line to add when `core.hooksPath` is set |
| Roundtable uninstalled but the hook remains | The hook warns and lets commits through |
| Branch names `rt/opus` and `rt/opus/T1` would clash in git | Seats rest on `rt/<seat>/idle`, tasks use `rt/<seat>/<task>` |
| Only one seat, or no seat can review | No critique or vote; reviews go to you |
| A review goes back and forth 3 times | The other seats vote; a tie goes to you |
| A planner never submits a draft | `rt watch` notifies you after 30 minutes; `rt plan continue` moves on |
| A dependency cycle or a bad path in the plan | Refused when drafted, naming the cycle or the path |
| A seat is paused or removed with work in progress | Its tasks return to ready and its leases are released; removing it also cancels its open review and critique assignments |
| Your app config already exists | Merged, never replaced; a timestamped backup is saved; unparseable files are left alone with an explanation |
| The app can't find `rt` on PATH | Configs use the full path of the installed Python |
| Database created by a newer Roundtable | Refused with an "upgrade Roundtable" message |
| A typo in `config.toml` | Refused, naming the setting and suggesting the right one |
| Text from one model tries to instruct another | Shown marked as data; commands only ever come from the plan you approved |
| New MCP protocol (2026-07-28) clients | Roundtable answers their opening `server/discover` probe with "method not found", so they fall back to the standard handshake. Tested with the official client 1.30.0 and 2.x, and with Claude Code 2.1.296 |
| The server can't find the project | It still starts and lists its tools; every call explains how to fix the setup |
| An unexpected bug | Logged to `.roundtable/logs/errors.log`; the model gets a clear error and its session keeps working |
