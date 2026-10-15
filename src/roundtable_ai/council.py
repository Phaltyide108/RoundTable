"""Ask the table: several AIs answer one question, rank each other's answers without names,
and the one whose answer ranked best writes the final answer.

This is Andrej Karpathy's LLM Council (independent answers, anonymous peer ranking, a chairman)
run with your own subscriptions instead of API keys, by the apps Roundtable can start itself
(Claude Code, Codex, opencode), and with your project open to them, read-only:

    1. answering  every chosen AI answers on its own, in parallel;
    2. ranking    each one sees all answers as Answer A, B, C (shuffled, no names), says what is
                  right and wrong in each and ends with a FINAL RANKING;
    3. combining  the author of the best-ranked answer (or the next in turn) writes the final
                  answer from all answers and reviews, fixing what the reviews found wrong.

The same machinery gives a failing task a second opinion ("rescue"): when a task fails its
tests twice in a row, an AI from another company reads the failure in the builder's own copy
of the project and sends the builder a diagnosis, as a suggestion it must answer.

A council runs in its own process (`rt _council Q1`), so the dashboard and the CLI only start it
and watch the database. Nothing here edits files: Claude Code runs with read-only tools and no
MCP servers, Codex with its read-only sandbox, opencode with edits and commands denied.
"""

from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from . import activity, events, util
from .errors import INVALID, NOT_FOUND, STATE, RTError
from .registry import HUMAN, Param, Result, op

RUNNABLE = ("claude-code", "codex-cli", "opencode")
LABELS = "ABCDEFGH"
READ_TOOLS = ["Read", "Glob", "Grep", "WebSearch", "WebFetch", "Bash(git log *)", "Bash(git show *)", "Bash(git diff *)",
              "Bash(git status *)", "Bash(ls *)", "Bash(python3 -c *)", "Bash(python -c *)"]   # python -c: to compute, not to change files
NO_EDITS = "Edit,Write,MultiEdit,NotebookEdit"
ANSWER_WORDS = 600
FINAL = ("done", "failed", "cancelled")


# ---------------------------------------------------------------- who can sit on a council

def eligible(ctx) -> list:
    """Active seats whose app Roundtable can run by itself, in the order they joined."""
    from .seats import limited_until

    return [r for r in ctx.db.all("SELECT * FROM seats WHERE status = 'active' ORDER BY created_at, handle")
            if r["app"] in RUNNABLE and not limited_until(ctx, r["handle"])]


def _get(ctx, cid: str):
    cid = str(cid or "").strip().upper()
    if cid and cid[0].isdigit():
        cid = "Q" + cid
    row = ctx.db.one("SELECT * FROM councils WHERE id = ?", (cid,))
    if row is None:
        raise RTError(NOT_FOUND, f"no question {cid or '(none)'}", "rt ask --list shows them")
    return row


# ---------------------------------------------------------------- operations

@op("council.ask", who=HUMAN, desc="Ask the table: every chosen AI answers on its own, they rank each other's answers without names, and the best writes the final answer",
    params=[Param("question", required=True, desc="what you want to know; the AIs can read the project but change nothing"),
            Param("seats", type="list", desc="who answers (default: every AI Roundtable can run)"),
            Param("follow_up", desc="the id of an earlier question this one follows, e.g. Q2")])
def ask(ctx, question, seats=None, follow_up=None) -> Result:
    question = util.cap_chars(util.require_text(question, "question"), 6000, "question")
    pool = {r["handle"]: r for r in eligible(ctx)}
    if seats:
        chosen = [util.check_handle(s) for s in seats]
        bad = [s for s in chosen if s not in pool]
        if bad:
            raise RTError(INVALID, f"{', '.join(bad)} can't answer here: only active AIs in Claude Code, Codex or opencode can",
                          f"choose from: {', '.join(pool) or 'none yet'}")
    else:
        chosen = list(pool)
    chosen = list(dict.fromkeys(chosen))
    if not chosen:
        raise RTError(STATE, "no AI here can answer by itself", "add an AI that runs in Claude Code, Codex or opencode")
    context = ""
    if follow_up:
        prev = _get(ctx, follow_up)
        if prev["final"]:
            context = f"This follows an earlier question.\nEarlier question: «{util.one_line(prev['question'], 1500)}»\nThe answer you gave together then:\n{prev['final'][:6000]}"
    with ctx.tx():
        cid = util.next_id(ctx.db, "council", "Q")
        now = util.now()
        ctx.db.execute("INSERT INTO councils(id, kind, question, context, members, stage, workdir, asked_by, created_at) VALUES (?, 'ask', ?, ?, ?, 'answering', ?, ?, ?)",
                       (cid, question, context, util.jdump(chosen), str(ctx.root), ctx.actor, now))
        for s in chosen:
            ctx.db.execute("INSERT INTO council_parts(council, seat, stage, status, started_at) VALUES (?, ?, 'answer', 'running', ?)", (cid, s, now))
        events.emit(ctx, "council.asked", f"{cid}: {util.one_line(question, 140)} · asked {', '.join(chosen)}", ref=cid)
    spawn(ctx, cid)
    who = ", ".join(chosen)
    how = "they rank each other's answers without names, then the best writes the final answer" if len(chosen) > 1 else "one AI answers (add more AIs for a council)"
    return Result(f"{cid} asked · {who} answer on their own now; {how}", {"id": cid, "seats": chosen})


@op("council.show", who=HUMAN, frozen_ok=True, desc="A question to the table: the final answer, how they ranked each other, and every answer",
    params=[Param("id", required=True), Param("all", type="bool", default=False, desc="also every answer and review in full")])
def show(ctx, id, all=False) -> Result:
    c = _get(ctx, id)
    d = detail(ctx, c["id"])
    lines = [f"{c['id']} [{c['stage']}] {c['question']}"]
    if d["ranking"]:
        lines.append("ranked by the others (best first): " + ", ".join(f"{r['seat']} (avg {r['avg']})" for r in d["ranking"]))
    if c["final"]:
        lines += [f"final answer (by {c['chair']}):", c["final"]]
    elif c["stage"] not in FINAL:
        lines.append("still " + {"answering": "answering", "ranking": "ranking the answers", "combining": "writing the final answer"}.get(c["stage"], c["stage"]))
    if c["error"]:
        lines.append("problem: " + c["error"])
    for p in d["parts"]:
        if p["status"] == "failed":
            lines.append(f"{p['seat']} ({p['stage']}) failed: {p['error']}")
    if all:
        for p in d["parts"]:
            if p["text"] and p["stage"] != "final":
                lines += ["", f"--- {p['seat']}: {p['stage']}" + (f" (Answer {p['label']})" if p["label"] else ""), p["text"]]
    return Result("\n".join(lines), {"council": d})


@op("council.list", who=HUMAN, frozen_ok=True, desc="Questions asked to the table, newest first",
    params=[Param("limit", type="int", default=20)])
def list_councils(ctx, limit=20) -> Result:
    rows = ctx.db.all("SELECT * FROM councils ORDER BY created_at DESC, id DESC LIMIT ?", (max(1, min(int(limit or 20), 200)),))
    if not rows:
        return Result("no questions yet: rt ask \"...\"", {"councils": []})
    lines = [f"{r['id']} [{r['stage']}]{' rescue ' + r['task'] if r['kind'] == 'rescue' else ''} {util.one_line(r['question'], 90)}" for r in rows]
    return Result("\n".join(lines), {"councils": [dict(r) for r in rows]})


@op("council.cancel", who=HUMAN, desc="Stop a question that is still being answered",
    params=[Param("id", required=True)])
def cancel(ctx, id) -> Result:
    c = _get(ctx, id)
    if c["stage"] in FINAL:
        raise RTError(STATE, f"{c['id']} is already {c['stage']}")
    with ctx.tx():
        ctx.db.execute("UPDATE councils SET stage = 'cancelled', finished_at = ? WHERE id = ?", (util.now(), c["id"]))
        ctx.db.execute("UPDATE council_parts SET status = 'failed', error = 'cancelled' WHERE council = ? AND status = 'running'", (c["id"],))
        events.emit(ctx, "council.cancelled", f"{c['id']} cancelled", ref=c["id"])
    _kill_group(c["pid"])
    return Result(f"{c['id']} cancelled")


# ---------------------------------------------------------------- what the dashboard shows

def summary(ctx, limit: int = 6) -> list[dict[str, Any]]:
    out = []
    for c in ctx.db.all("SELECT * FROM councils ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)):
        parts = [dict(p) for p in ctx.db.all("SELECT seat, stage, status, label, error, tokens FROM council_parts WHERE council = ?", (c["id"],))]
        members = []
        for s in util.jload(c["members"], []):
            mine = {p["stage"]: p for p in parts if p["seat"] == s}
            answer, rank, final = mine.get("answer") or {}, mine.get("rank") or {}, mine.get("final") or {}
            members.append({"seat": s, "answer": answer.get("status"), "rank": rank.get("status"), "final": final.get("status"),
                            "label": answer.get("label"), "error": next((p["error"] for p in mine.values() if p["status"] == "failed"), None)})
        out.append({"id": c["id"], "kind": c["kind"], "question": c["question"], "stage": c["stage"], "chair": c["chair"], "task": c["task"],
                    "final": (c["final"] or "")[:1600], "final_long": len(c["final"] or "") > 1600, "members": members,
                    "ranking": util.jload(c["ranking"], []), "error": c["error"], "at": util.local_hm(c["created_at"]),
                    "created_at": c["created_at"], "tokens": sum(int(p["tokens"] or 0) for p in parts)})
    return out


def detail(ctx, cid: str) -> dict[str, Any]:
    c = _get(ctx, cid)
    parts = [dict(p) for p in ctx.db.all("SELECT * FROM council_parts WHERE council = ? ORDER BY CASE stage WHEN 'answer' THEN 0 WHEN 'rank' THEN 1 ELSE 2 END, label, seat", (c["id"],))]
    for p in parts:
        p["ranking"] = util.jload(p["ranking"], [])
    return {"id": c["id"], "kind": c["kind"], "question": c["question"], "stage": c["stage"], "chair": c["chair"], "final": c["final"] or "",
            "members": util.jload(c["members"], []), "ranking": util.jload(c["ranking"], []), "error": c["error"], "task": c["task"],
            "at": util.local_hm(c["created_at"]), "parts": parts, "tokens": sum(int(p["tokens"] or 0) for p in parts)}


# ---------------------------------------------------------------- starting the worker

def spawn(ctx, cid: str) -> None:
    if os.environ.get("RT_COUNCIL_INLINE") == "1":       # tests: run in this process
        run_council(ctx.home, cid)
        return
    log = Path(ctx.home) / "logs" / f"council-{cid}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.pop("RT_SEAT", None)
    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "cwd": str(ctx.root), "env": env}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000
    else:
        kwargs["start_new_session"] = True
    with open(log, "ab") as fh:
        p = subprocess.Popen([sys.executable, "-m", "roundtable_ai", "--home", str(ctx.home), "_council", cid],
                             stdout=fh, stderr=subprocess.STDOUT, **kwargs)
    with ctx.tx():
        ctx.db.execute("UPDATE councils SET pid = ? WHERE id = ?", (p.pid, cid))


def _kill_group(pid) -> None:
    if not pid:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        else:
            import signal

            os.killpg(int(pid), signal.SIGTERM)
    except Exception:
        pass


def main(argv: list[str]) -> int:
    """`python -m roundtable_ai --home H _council Q1` (started by spawn)."""
    home = None
    if "--home" in argv:
        i = argv.index("--home")
        home = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if not argv:
        return 2
    run_council(home, argv[0])
    return 0


# ---------------------------------------------------------------- one AI, headless and read-only

def command(row, prompt: str, cwd: Path) -> tuple[list[str], dict[str, str]]:
    from . import launch
    from .config import toml_value

    app, model = row["app"], row["model"]
    effort = launch._effort(row)
    if app == "claude-code":
        cmd = [launch._exe("claude"), "-p", prompt, "--output-format", "stream-json", "--verbose", "--model", model]
        if effort:
            cmd += ["--effort", effort]
        return cmd + ["--permission-mode", "default", "--allowedTools", ",".join(READ_TOOLS), "--disallowedTools", NO_EDITS,
                      "--strict-mcp-config"], {}
    if app == "codex-cli":
        cmd = [launch._exe("codex"), "exec", "--json", "-m", model, "-s", "read-only", "-C", str(cwd), "--skip-git-repo-check"]
        if effort:
            cmd += ["-c", f"model_reasoning_effort={toml_value(effort)}"]
        return cmd + [prompt], {}
    if app == "opencode":
        cmd = [launch._exe("opencode"), "run", "--format", "json", "--dir", str(cwd), "-m", model]
        if effort:
            cmd += ["--variant", effort]
        perms = {"edit": "deny", "webfetch": "allow",
                 "bash": {"*": "deny", "git log*": "allow", "git show*": "allow", "git diff*": "allow", "git status*": "allow", "ls*": "allow",
                          "python3 -c*": "allow", "python -c*": "allow"}}
        return cmd + [prompt], {"OPENCODE_PERMISSION": json.dumps(perms)}
    raise RTError(INVALID, f"Roundtable can't run {app} by itself")


class _Collector:
    """Reads one app's JSON stream: the final text, tokens, activity for the dashboard."""

    def __init__(self, app: str, root: str):
        self.app, self.root = app, root
        self.result: str | None = None      # claude: the result event
        self.messages: list[str] = []       # codex: agent messages
        self.texts: list[tuple[int, str]] = []  # opencode: (tool count when said, text)
        self.tools = 0
        self.tokens = 0
        self.error: str | None = None

    def feed(self, line: str) -> list[dict]:
        from . import runner

        items, facts = runner._parse_line(self.app, line, self.root)
        if "tokens_add" in facts:
            self.tokens += int(facts["tokens_add"] or 0)
        elif facts.get("tokens") and self.app != "opencode":
            self.tokens += int(facts["tokens"])
        try:
            ev = json.loads(line)
        except ValueError:
            return items
        if not isinstance(ev, dict):
            return items
        t = ev.get("type")
        if self.app == "claude-code" and t == "result":
            if ev.get("is_error") or (ev.get("subtype") and ev.get("subtype") != "success"):
                self.error = util.one_line(str(ev.get("result") or ev.get("subtype") or "the run failed"), 300)
            else:
                self.result = str(ev.get("result") or "")
        elif self.app == "codex-cli":
            item = ev.get("item") or {}
            if t == "item.completed" and item.get("type") in ("agent_message", "assistant_message") and item.get("text"):
                self.messages.append(str(item["text"]))
            if t in ("turn.failed", "error"):
                err = ev.get("error") if isinstance(ev.get("error"), dict) else {}
                self.error = util.one_line(str(err.get("message") or ev.get("message") or "the run failed"), 300)
        elif self.app == "opencode":
            part = ev.get("part") if isinstance(ev.get("part"), dict) else {}
            if t == "tool_use":
                self.tools += 1
            elif t == "text" and part.get("text"):
                self.texts.append((self.tools, str(part["text"])))
            elif t == "error":
                err = ev.get("error") if isinstance(ev.get("error"), dict) else {}
                data = err.get("data") if isinstance(err.get("data"), dict) else {}
                self.error = util.one_line(str(data.get("message") or err.get("name") or "the run failed"), 300)
        return items

    def text(self) -> str:
        if self.app == "claude-code":
            return (self.result or "").strip()
        if self.app == "codex-cli":
            return (self.messages[-1] if self.messages else "").strip()
        after = [t for n, t in self.texts if n == self.tools] or [t for _n, t in self.texts]
        return "\n\n".join(x.strip() for x in after if x.strip())


def run_member(home: Path, row, prompt: str, cwd: Path, *, what: str, minutes: int) -> dict[str, Any]:
    """Run one AI once, read-only. Returns {"text", "tokens", "seconds", "error"}."""
    from . import runner

    handle = row["handle"]
    started = time.time()
    try:
        cmd, extra = command(row, prompt, cwd)
    except RTError as exc:
        return {"text": "", "tokens": 0, "seconds": 0.0, "error": exc.message + (f" ({exc.hint})" if exc.hint else "")}
    env = runner.clean_env(os.environ)
    env.update(extra)
    kwargs: dict[str, Any] = {"cwd": str(cwd), "env": env, "stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000200 | 0x08000000
    else:
        kwargs["start_new_session"] = True
    activity.append(home, handle, [{"kind": "start", "text": what}])
    col = _Collector(row["app"], str(cwd))
    try:
        proc = subprocess.Popen(cmd, **kwargs)
    except OSError as exc:
        return {"text": "", "tokens": 0, "seconds": 0.0, "error": f"could not start {row['app']}: {exc}"}
    err_tail: list[str] = []

    def drain_err():
        assert proc.stderr is not None
        for raw in proc.stderr:
            err_tail.append(raw.decode("utf-8", errors="replace").rstrip())
            del err_tail[:-6]

    t = threading.Thread(target=drain_err, daemon=True)
    t.start()
    timer = threading.Timer(max(1, minutes) * 60, lambda: runner._kill(proc))
    timer.daemon = True
    timer.start()
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            items = col.feed(line)
            if items:
                activity.append(home, handle, items)
        proc.wait()
    finally:
        timer.cancel()
    t.join(2)
    seconds = round(time.time() - started, 1)
    text = col.text()
    error = None
    if seconds >= max(1, minutes) * 60:
        error = f"stopped after {minutes} minutes (council.max_minutes)"
    elif not text:
        tail = " / ".join(x for x in err_tail if x.strip())[-300:]
        error = col.error or (f"{row['app']} exited with {proc.returncode}: {tail}" if tail or proc.returncode else "it gave no answer")
    return {"text": text, "tokens": col.tokens, "seconds": seconds, "error": error}


# ---------------------------------------------------------------- prompts

def _project_line(cwd: Path) -> str:
    return (f"You are in the project folder {cwd}. You may read any file in it, use git log/show/diff to look at history, and run "
            "short `python3 -c` computations to check facts and numbers, but change nothing: no edits, no commits, no files written.")


def answer_prompt(row, c, n: int) -> str:
    others = "the other AIs" if n > 1 else "nobody else"
    lines = [f"You are {row['handle']} ({row['model']}), one of {n} AI model{'s' if n != 1 else ''} from different companies answering the same question for a person, independently.",
             f"You cannot see {others}' answers; afterwards every answer is ranked by all of you without names." if n > 1 else "",
             _project_line(Path(c["workdir"]))]
    if c["context"]:
        lines += ["", c["context"]]
    lines += ["", "The question (the person's words, in full):", f"«{c['question']}»", "",
              "Answer as well as you can. Be concrete and correct. When the question is about this project, check the code and name the files "
              f"you looked at. Say plainly what you are unsure of. Keep it under {ANSWER_WORDS} words unless the question needs more. "
              "Reply with the answer only."]
    return "\n".join(x for x in lines if x is not None)


def _answers_block(answers: list[tuple[str, str]]) -> str:
    return "\n\n".join(f"Answer {label}:\n<<<\n{text.strip()}\n>>>" for label, text in answers)


def disagreements(answers: list[tuple[str, str]]) -> list[str]:
    """For answers given as numbered items ("3: 42"), the item numbers where they don't all say the same thing."""
    parsed: list[dict[str, str]] = []
    for _label, text in answers:
        items = {}
        for line in str(text or "").splitlines():
            m = re.match(r"^\s*\**\s*(\d{1,3})\s*[:.)]\s*(.+?)\s*$", line)
            if m and m.group(1) not in items:
                items[m.group(1)] = re.sub(r"[\s*`_.,]+", "", m.group(2).lower())
        if len(items) < 3:
            return []
        parsed.append(items)
    keys = sorted({k for p in parsed for k in p}, key=int)
    return [k for k in keys if len({p.get(k, "") for p in parsed}) > 1]


def _dispute_note(answers: list[tuple[str, str]], who: str) -> str:
    items = disagreements(answers)
    if not items:
        return ""
    return (f"The answers disagree on item{'s' if len(items) > 1 else ''} {', '.join(items)}. {who} work out each of these again from scratch, "
            "step by step, and decide on the merits, not by which answer seems better overall. When an item can be computed, compute it with python3 -c.")


def rank_prompt(c, answers: list[tuple[str, str]]) -> str:
    labels = [a for a, _t in answers]
    note = _dispute_note(answers, "Before ranking,")
    return "\n".join([
        f"Several AI models answered the question below on their own. Their {len(answers)} answers are shown as Answer {', '.join(labels)}, "
        "in random order and without names. One of them may be yours: judge it by the same standard as the others.",
        _project_line(Path(c["workdir"])), "",
        "The question:", f"«{c['question']}»", "",
        _answers_block(answers), "",
        *([note + " Say which answer, if any, has each of them right.", ""] if note else []),
        "For each answer, say in two to four short lines what it gets right, what is wrong or missing, and whether its claims hold up "
        "(check the project files when that settles it). Be strict about correctness. Then end with exactly this, every answer once, best first:",
        "FINAL RANKING:", *[f"{i}. Answer {label}" for i, label in enumerate(labels, 1)]])


def final_prompt(c, answers: list[tuple[str, str]], reviews: list[str], best: str | None) -> str:
    lines = ["You write the final answer for a council of AI models from different companies. They answered the question below "
             "independently; then each one reviewed and ranked all the answers without knowing who wrote which."
             + (f" Their rankings put Answer {best} first." if best else ""),
             _project_line(Path(c["workdir"]))]
    if c["context"]:
        lines += ["", c["context"]]
    lines += ["", "The question (the person's words, in full):", f"«{c['question']}»", "", _answers_block(answers), ""]
    lines += [f"Review {i}:\n<<<\n{r.strip()}\n>>>" for i, r in enumerate(reviews, 1)]
    note = _dispute_note(answers, "Before writing,")
    if note:
        lines += ["", note + " The best-ranked answer can still be wrong on some of them; where a review shows how to get an item right, check that working."]
    lines += ["", "Write the single best answer for the person: keep what the answers got right, fix what the reviews showed is wrong, "
              "and add what all of them missed (check the code when in doubt). If the models still disagree on something that matters, "
              "say so in one line and say which view is right and why. Keep the format the question asked for. Do not mention Answer A/B or the reviews. "
              "Reply with the final answer only."]
    return "\n".join(lines)


def rescue_prompt(c) -> str:
    return "\n".join([
        "You are giving a second opinion to another AI model from a different company. Its task keeps failing its tests and it may be stuck.",
        f"You are in its copy of the project: {c['workdir']}. Read whatever you need (the code, the tests, git diff and git log), "
        "but change nothing: no edits, no commits.", "",
        c["context"], "",
        "Find the most likely cause of the failure. Reply with a short diagnosis for the builder (under 250 words): what is wrong, "
        "in which file and where, and the smallest fix. If the test itself looks wrong, say so and why. No preamble."])


# ---------------------------------------------------------------- the ranking

def parse_ranking(text: str, labels: list[str]) -> list[str]:
    """Labels in the order the review ranked them, from its FINAL RANKING section (or the whole text as a fallback)."""
    part = text.split("FINAL RANKING:")[-1] if "FINAL RANKING:" in text else ""
    found = re.findall(r"Answer\s+([A-H])\b", part) or (re.findall(r"^\s*\d+[.)]\s*Answer\s+([A-H])\b", text, re.M))
    out: list[str] = []
    for x in found:
        if x in labels and x not in out:
            out.append(x)
    return out


def aggregate(rankings: list[list[str]], labels: list[str]) -> list[dict[str, Any]]:
    """Average position of each answer over all rankings (1 = best), best first."""
    pos: dict[str, list[int]] = {label: [] for label in labels}
    firsts = {label: 0 for label in labels}
    for r in rankings:
        for i, label in enumerate(r, 1):
            pos[label].append(i)
        if r:
            firsts[r[0]] += 1
    rows = [{"label": label, "avg": round(sum(p) / len(p), 2) if p else None, "votes": len(p), "firsts": firsts[label]} for label, p in pos.items()]
    rows.sort(key=lambda r: (r["avg"] if r["avg"] is not None else 99, -r["firsts"], r["label"]))
    return rows


# ---------------------------------------------------------------- the worker

def _stage(home, cid: str) -> str:
    from .context import open_ctx

    ctx = open_ctx(home, client="council")
    try:
        row = ctx.db.one("SELECT stage FROM councils WHERE id = ?", (cid,))
        return row["stage"] if row else "cancelled"
    finally:
        ctx.close()


def _save_part(home, cid: str, seat: str, stage: str, res: dict[str, Any], **extra) -> None:
    from .context import open_ctx

    ctx = open_ctx(home, client="council")
    try:
        with ctx.tx():
            cols = {"text": res.get("text") or "", "status": "failed" if res.get("error") else "done", "error": res.get("error"),
                    "tokens": int(res.get("tokens") or 0), "seconds": res.get("seconds"), "finished_at": util.now(), **extra}
            ctx.db.execute("INSERT OR IGNORE INTO council_parts(council, seat, stage, started_at) VALUES (?,?,?,?)", (cid, seat, stage, util.now()))
            ctx.db.execute(f"UPDATE council_parts SET {', '.join(k + ' = ?' for k in cols)} WHERE council = ? AND seat = ? AND stage = ?",
                           (*cols.values(), cid, seat, stage))
    finally:
        ctx.close()


def _parallel(jobs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Run (key, fn) jobs at once; returns key -> result."""
    out: dict[str, Any] = {}

    def run(key, fn):
        try:
            out[key] = fn()
        except Exception as exc:  # noqa: BLE001 - becomes this member's error
            out[key] = {"text": "", "tokens": 0, "seconds": 0.0, "error": f"Roundtable failed: {exc}"}

    threads = [threading.Thread(target=run, args=job, daemon=True) for job in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


def run_council(home, cid: str) -> None:
    """Run every stage of one council. Never raises: problems are recorded on the council."""
    from .context import open_ctx

    ctx = open_ctx(home, client="council")
    try:
        c = _get(ctx, cid)
        if c["stage"] in FINAL:
            return
        home = ctx.home
        seats = {r["handle"]: r for r in ctx.db.all("SELECT * FROM seats")}
        members = [seats[s] for s in util.jload(c["members"], []) if s in seats]
        minutes = int(ctx.setting("council", "max_minutes"))
        chair_mode = ctx.setting("council", "chair")
        n_before = ctx.db.scalar("SELECT COUNT(*) FROM councils WHERE kind = 'ask' AND created_at < ?", (c["created_at"],), 0)
    finally:
        ctx.close()
    workdir = Path(c["workdir"] or ".")
    try:
        if c["kind"] == "rescue":
            _run_rescue(home, c, members[0], workdir, minutes)
            return
        # 1. everyone answers on their own
        results = _parallel([(m["handle"], (lambda m=m: run_member(home, m, answer_prompt(m, c, len(members)), workdir,
                                                                    what=f"answering question {cid}", minutes=minutes))) for m in members])
        if _stage(home, cid) == "cancelled":
            return
        good = [m for m in members if not results[m["handle"]]["error"]]
        order = good[:]
        random.shuffle(order)
        label_of = {m["handle"]: LABELS[i] for i, m in enumerate(order)}
        for m in members:
            _save_part(home, cid, m["handle"], "answer", results[m["handle"]], label=label_of.get(m["handle"]))
        if not good:
            _finish(home, cid, "failed", error="no AI could answer: " + "; ".join(f"{m['handle']}: {results[m['handle']]['error']}" for m in members))
            return
        if len(good) == 1:
            only = good[0]
            _finish(home, cid, "done", final=results[only["handle"]]["text"], chair=only["handle"],
                    note=f"only {only['handle']} answered, so its answer is the final one")
            return
        answers = [(label_of[m["handle"]], results[m["handle"]]["text"]) for m in order]
        labels = [a for a, _t in answers]
        # 2. each one ranks all the answers, without names
        _set_stage(home, cid, "ranking", f"{cid}: {len(good)} answers in; each AI now ranks them without names")
        reviews = _parallel([(m["handle"], (lambda m=m: run_member(home, m, rank_prompt(c, answers), workdir,
                                                                    what=f"ranking the answers to {cid}", minutes=minutes))) for m in good])
        if _stage(home, cid) == "cancelled":
            return
        rankings: list[list[str]] = []
        review_texts: list[str] = []
        for m in good:
            r = reviews[m["handle"]]
            ranked = parse_ranking(r["text"], labels) if not r["error"] else []
            _save_part(home, cid, m["handle"], "rank", r, ranking=util.jdump(ranked))
            if ranked:
                rankings.append(ranked)
            if r["text"]:
                review_texts.append(r["text"].split("FINAL RANKING:")[0].strip())
        table = aggregate(rankings, labels)
        seat_of = {v: k for k, v in label_of.items()}
        for row in table:
            row["seat"] = seat_of[row["label"]]
        best = table[0]["label"] if rankings else None
        if chair_mode == "rotate" or best is None:
            chair = good[n_before % len(good)]["handle"]
        else:
            chair = seat_of[best]
        # 3. the chair writes the final answer
        _set_stage(home, cid, "combining", f"{cid}: ranked; {chair} writes the final answer", chair=chair, ranking=table)
        chair_row = next(m for m in good if m["handle"] == chair)
        fin = run_member(home, chair_row, final_prompt(c, answers, review_texts, best), workdir,
                         what=f"writing the final answer to {cid}", minutes=minutes)
        _save_part(home, cid, chair, "final", fin)
        if _stage(home, cid) == "cancelled":
            return
        if fin["error"]:
            # fall back to the best-ranked answer rather than nothing
            fallback = dict(answers)[best] if best else answers[0][1]
            _finish(home, cid, "done", final=fallback, chair=seat_of.get(best or "", chair),
                    note=f"{chair} could not write the final answer ({fin['error']}); the best-ranked answer stands")
            return
        _finish(home, cid, "done", final=fin["text"], chair=chair)
    except Exception as exc:  # noqa: BLE001 - recorded for the person
        _finish(home, cid, "failed", error=f"Roundtable failed: {exc!r}")


def _set_stage(home, cid: str, stage: str, text: str, chair: str | None = None, ranking: list | None = None) -> None:
    from .context import open_ctx

    ctx = open_ctx(home, client="council")
    try:
        with ctx.tx():
            ctx.db.execute("UPDATE councils SET stage = ?, chair = COALESCE(?, chair), ranking = COALESCE(?, ranking) WHERE id = ? AND stage NOT IN ('cancelled')",
                           (stage, chair, util.jdump(ranking) if ranking is not None else None, cid))
            events.emit(ctx, "council." + stage, text, ref=cid, actor="system")
    finally:
        ctx.close()


def _finish(home, cid: str, stage: str, *, final: str | None = None, chair: str | None = None, error: str | None = None, note: str = "") -> None:
    from .context import open_ctx

    ctx = open_ctx(home, client="council")
    try:
        with ctx.tx():
            row = ctx.db.one("SELECT stage FROM councils WHERE id = ?", (cid,))
            if row is None or row["stage"] == "cancelled":
                return
            ctx.db.execute("UPDATE councils SET stage = ?, final = COALESCE(?, final), chair = COALESCE(?, chair), error = ?, finished_at = ? WHERE id = ?",
                           (stage, final, chair, error or (note or None), util.now(), cid))
            if stage == "done":
                events.emit(ctx, "council.done", f"{cid} answered" + (f" · final answer by {chair}" if chair else "") + (f" · {note}" if note else ""),
                            ref=cid, actor=chair or "system")
            else:
                events.emit(ctx, "council.failed", f"{cid} could not be answered: {util.one_line(error or '', 200)}", ref=cid, actor="system", level=2)
    finally:
        ctx.close()


# ---------------------------------------------------------------- second opinion on a failing task

def failures_in_a_row(ctx, task_id: str) -> int:
    n = 0
    for r in ctx.db.all("SELECT status FROM proof_runs WHERE task = ? ORDER BY created_at DESC, id DESC LIMIT 10", (task_id,)):
        if r["status"] in ("failed", "timeout"):
            n += 1
        elif r["status"] in ("passed",):
            break
    return n


def pick_helper(ctx, owner_row):
    """An AI Roundtable can run, not the owner, from another company if there is one."""
    pool = [r for r in eligible(ctx) if r["handle"] != owner_row["handle"]]
    other = [r for r in pool if r["company"] != owner_row["company"]]
    return (other or pool or [None])[0]


def maybe_rescue(ctx, task_id: str) -> str | None:
    """After a failed proof: when it is the second failure in a row, ask another AI for a diagnosis. Returns the council id."""
    if not ctx.setting("council", "rescue"):
        return None
    t = ctx.db.one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    if t is None or not t["owner"] or failures_in_a_row(ctx, task_id) < 2:
        return None
    last_pass = ctx.db.scalar("SELECT MAX(created_at) FROM proof_runs WHERE task = ? AND status = 'passed'", (task_id,), None) or ""
    if ctx.db.one("SELECT 1 FROM councils WHERE kind = 'rescue' AND task = ? AND created_at > ?", (task_id, last_pass)):
        return None                  # one second opinion per losing streak
    owner = ctx.db.one("SELECT * FROM seats WHERE handle = ?", (t["owner"],))
    helper = pick_helper(ctx, owner) if owner is not None else None
    if helper is None:
        return None
    run = ctx.db.one("SELECT * FROM proof_runs WHERE task = ? ORDER BY created_at DESC, id DESC LIMIT 1", (task_id,))
    workdir = (run["workdir"] if run and run["workdir"] else None) or (owner["worktree"] or str(ctx.root))
    context = "\n".join([
        f"The task: {t['id']} {t['title']}",
        f"What it should do: {t['summary'] or '(no summary)'}",
        f"Files it may change: {', '.join(util.jload(t['files'], []))}",
        f"Its test command: {' && '.join(util.jload(t['proof'], []))}",
        f"It has failed {failures_in_a_row(ctx, task_id)} times in a row. The last failure"
        + (f" (at `{run['failed_cmd']}`)" if run and run["failed_cmd"] else "") + ":",
        "<<<", (run["output_tail"] if run else "") or "(no output)", ">>>"])
    with ctx.tx():
        cid = util.next_id(ctx.db, "council", "Q")
        now = util.now()
        ctx.db.execute("INSERT INTO councils(id, kind, question, context, task, members, chair, stage, workdir, asked_by, created_at) "
                       "VALUES (?, 'rescue', ?, ?, ?, ?, ?, 'answering', ?, 'system', ?)",
                       (cid, f"Why does {t['id']} keep failing its tests?", context, t["id"], util.jdump([helper["handle"]]), helper["handle"], workdir, now))
        ctx.db.execute("INSERT INTO council_parts(council, seat, stage, status, started_at) VALUES (?, ?, 'answer', 'running', ?)", (cid, helper["handle"], now))
        events.emit(ctx, "council.rescue", f"{t['id']} failed its tests twice in a row: {helper['handle']} takes a look ({cid})",
                    ref=cid, task=t["id"], actor="system")
    try:
        spawn(ctx, cid)
    except OSError:
        return None
    return cid


def _run_rescue(home, c, helper, workdir: Path, minutes: int) -> None:
    from . import suggestions
    from .context import open_ctx, with_actor

    res = run_member(home, helper, rescue_prompt(c), workdir, what=f"looking at why {c['task']} fails ({c['id']})", minutes=minutes)
    _save_part(home, c["id"], helper["handle"], "answer", res, label="A")
    if res["error"]:
        _finish(home, c["id"], "failed", error=f"{helper['handle']}: {res['error']}")
        return
    _finish(home, c["id"], "done", final=res["text"], chair=helper["handle"])
    ctx = open_ctx(home, client="council")
    try:
        t = ctx.db.one("SELECT * FROM tasks WHERE id = ?", (c["task"],))
        if t is not None and t["owner"] and t["status"] not in ("done", "cancelled"):
            text = f"Second opinion on why {t['id']} fails its tests (from {helper['handle']}, asked by Roundtable):\n{res['text']}"
            suggestions.send(with_actor(ctx, helper["handle"], "council"), text=text[: ctx.setting("limits", "text_chars")], task=t["id"])
    except RTError:
        pass
    finally:
        ctx.close()

