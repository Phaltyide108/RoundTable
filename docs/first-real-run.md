# First real run: Claude and GPT build Roundtable together

This walks you through a real session on this very repository: Claude (in Claude Code) and GPT-6.1 Sol (in Codex CLI) plan, build and review two small features from [comparison.md](comparison.md), and you approve. Commands are for Linux/macOS and can be pasted as they are.

You need: a Claude Pro/Max plan (for Claude Code), a ChatGPT Plus/Pro plan (for Codex with GPT-6.1 Sol), git, curl.

## 1. Get the repository

```bash
cd ~/Desktop
git clone https://github.com/Phaltyide108/RoundTable.git
cd RoundTable
```

Roundtable will create one working folder per coding model next to it: `~/Desktop/RoundTable.opus` and `~/Desktop/RoundTable.sol`.

## 2. Install Roundtable, Claude Code and Codex

```bash
sh scripts/install.sh                          # Roundtable (installs uv for you if needed, no sudo)
curl -fsSL https://claude.ai/install.sh | bash   # Claude Code
```

Open a **new terminal** so both are on your PATH, then check:

```bash
rt --version
claude --version
codex --version || npm install -g @openai/codex
```

Log in once to each, then quit:

- `claude` → follow the browser login → type `/exit`.
- `codex` → sign in with ChatGPT → type `/model` and check that **gpt-6.1-sol** is listed (it reaches accounts gradually; if it is missing, note the name of the model you want to use instead) → press Ctrl+C.

Make sure git knows who you are (skips anything already set):

```bash
git config --global user.name >/dev/null || git config --global user.name "Phaltyide108"
git config --global user.email >/dev/null || git config --global user.email "104723892+Phaltyide108@users.noreply.github.com"
```

## 3. Set up the table (dashboard)

```bash
cd ~/Desktop/RoundTable
rt ui
```

Your browser opens the dashboard.

1. Click **Set up Roundtable in this folder**.
2. **Models → Add a model**: name `opus`, where it runs **Claude Code in a terminal**, model `claude-opus-5-5`. **Add model**.
3. **Add a model** again: name `sol`, **Codex in a terminal**, model `gpt-6.1-sol` (or the name `/model` showed). **Add model**.
4. Click **Start in a terminal** on each. A terminal window opens per model, already in its own folder and joined. Allow the roundtable tools when the app asks.

Terminal alternative: `rt init`, `rt seat add opus --model claude-opus-5-5 --app claude-code`, `rt seat add sol --model gpt-6.1-sol --app codex-cli`, then `rt launch opus` and `rt launch sol` in two terminals.

## 4. Give them the goal

**Plan → Start a plan.** Paste this as the goal, choose **Mid** review depth, click **Start planning**:

```text
Close two gaps from docs/comparison.md, each with tests and following AGENTS.md. (1) Text search in the event log: rt log --grep TEXT, case-insensitive, combinable with --since and --task. (2) Database backups: rt backup copies the project's Roundtable database with the sqlite3 backup API into .roundtable/backups/ with a timestamped name and keeps the newest 10; rt doctor reports the age of the newest backup. Use this proof command for every task: uv run --no-project --python 3.12 --with pytest -- python -m pytest -q. docs/cli.md is generated: only the last task regenerates it with python scripts/gen_docs.py.
```

Terminal alternative: `rt goal "<the text above>" --review mid`.

## 5. Watch and decide

- **Overview** shows what needs you, and the table: who is writing, critiquing, working or reviewing.
- When the plan is ready, **Overview** says so. Open **Plan**, read the tasks and the test commands, tick the box, **Lock the plan** (terminal: `rt plan view`, `rt plan lock`).
- Then each model claims a task, works in its own folder, and closes it. Roundtable runs the tests; the other model reviews; the task merges into `main`.
- If a model files a bug it found, it appears in **Tasks → Backlog**: accept it or cancel it.

## 6. Keep them moving

The models do not listen in the background. When a terminal goes quiet, type `check roundtable` in it. The dashboard and `rt watch` tell you when something needs you.

## 7. Watch the cost

```bash
rt usage
```

(or the **Usage** page). This shows, per model: context used, session tokens, the 5-hour and 7-day plan limits, and what the exchange through Roundtable itself cost. Claude Code also shows a one-line version at the bottom of its window. For Codex, the numbers come from its session logs and appear after its first reply.

## 8. If something goes wrong

- `rt doctor` explains most problems and the fix.
- Codex asks to run `git commit` outside its sandbox: that is expected (its sandbox keeps `.git` read-only). Approve it, or tell it: "use commit=true when you checkpoint or close".
- A seat says it is "live in another chat" after you closed it: `rt seat release opus` (or `sol`).
- Stop everything at once: `rt freeze`, later `rt unfreeze`.

## 9. Share the result

When it is done (or stuck), run:

```bash
rt status
rt usage
rt export
```

and send the output (and the folder `rt export` names) back for review. To publish the merged work: `git push` from `~/Desktop/RoundTable` (needs your GitHub login on this computer, e.g. `gh auth login`).
