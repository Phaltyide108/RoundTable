"""`rt bench`: does a team of AIs do better than one?

The same task (a written specification) is given to:
- each AI working alone, started headless in a fresh copy of a starter project,
  with no Roundtable at all;
- a team at a Roundtable in another fresh copy: they plan (or split the work
  quickly), build, test and check each other, all in background runs.

Afterwards Roundtable runs hidden tests the contenders never saw against what
each produced, and writes a report: tests passed, minutes, tokens. Everything
runs on this computer with your own Claude Code and Codex logins, so a run uses
real limits; contenders run one after the other so they don't compete for them.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import INVALID, NOT_FOUND, RTError

TASKS_DIR = Path(__file__).parent / "bench"
DEFAULT_MODELS = {"claude-code": "claude-opus-5-5", "codex-cli": "gpt-6.1-sol"}
ALIASES = {"claude": "claude-code", "claude-code": "claude-code", "codex": "codex-cli", "codex-cli": "codex-cli"}
SOLO_TOOLS = ["Read", "Edit", "Write", "MultiEdit", "Glob", "Grep", "TodoWrite", "Bash(python *)", "Bash(python3 *)",
              "Bash(ls *)", "Bash(cat *)", "Bash(git status *)", "Bash(git diff *)", "Bash(git add *)", "Bash(git commit *)"]


@dataclass
class Member:
    app: str
    model: str
    effort: str | None = None

    @property
    def label(self) -> str:
        return pretty_model(self.model) + (f" ({self.effort})" if self.effort else "")


def pretty_model(m: str) -> str:
    """claude-opus-5-5 -> Claude Opus 5.5, gpt-6.1-sol -> GPT-6.1 Sol"""
    out: list[str] = []
    parts = [p for p in re.split(r"[-_ ]+", m) if p]
    i = 0
    while i < len(parts):
        p = parts[i]
        if p[0].isdigit():
            n = p
            while p.isdigit() and i + 1 < len(parts) and parts[i + 1].isdigit():
                i += 1
                n += "." + parts[i]
            if out and out[-1] == "GPT":
                out[-1] = "GPT-" + n
            else:
                out.append(n)
        else:
            out.append("GPT" if p.lower() == "gpt" else p[:1].upper() + p[1:])
        i += 1
    return " ".join(out)


@dataclass
class Contender:
    kind: str                 # solo | team
    members: list[Member]
    result: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        names = " + ".join(m.label for m in self.members)
        return f"{names} alone" if self.kind == "solo" else f"Team: {names}"


def tasks() -> list[str]:
    return sorted(p.name for p in TASKS_DIR.iterdir() if (p / "task.md").exists()) if TASKS_DIR.is_dir() else []


def parse_member(text: str) -> Member:
    """claude | codex | claude:high | claude:claude-sonnet-5-5:medium | codex-cli:gpt-6.1-sol:xhigh"""
    from .apps import EFFORTS

    parts = [p for p in str(text).strip().split(":") if p]
    if not parts or parts[0].lower() not in ALIASES:
        raise RTError(INVALID, f"unknown contender {text!r}", "use claude or codex, optionally :model and :effort, e.g. claude:high or codex:gpt-6.1-sol:xhigh")
    app = ALIASES[parts[0].lower()]
    model, effort = DEFAULT_MODELS[app], None
    for p in parts[1:]:
        if p.lower() in EFFORTS[app]:
            effort = p.lower()
        else:
            model = p
    return Member(app, model, effort)


def task_text(task: str) -> str:
    path = TASKS_DIR / task / "task.md"
    if not path.exists():
        raise RTError(NOT_FOUND, f"no benchmark task {task!r}", f"tasks: {', '.join(tasks()) or 'none'}")
    return path.read_text(encoding="utf-8")


def prepare_repo(task: str, dest: Path) -> Path:
    """A fresh git repository with the task's starter files and its specification as TASK.md."""
    src = TASKS_DIR / task / "starter"
    dest.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=True)
    (dest / "TASK.md").write_text(task_text(task), encoding="utf-8")

    def git(*a):
        subprocess.run(["git", "-C", str(dest), *a], check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "bench@roundtable.local")
    git("config", "user.name", "Roundtable bench")
    git("config", "commit.gpgsign", "false")
    git("add", "-A")
    git("commit", "-q", "-m", "starter")
    return dest


# ---------------------------------------------------------------- scoring

_RUNNER = r'''
import io, json, sys, unittest
sys.path.insert(0, ".")
suite = unittest.defaultTestLoader.loadTestsFromName("_hidden.test_hidden")
res = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
failed = [t.id().split(".", 2)[-1] for t, _ in res.failures + res.errors]
print(json.dumps({"run": res.testsRun, "failed": failed}))
'''


def count_hidden(task: str) -> int:
    text = (TASKS_DIR / task / "hidden" / "test_hidden.py").read_text(encoding="utf-8")
    return len(re.findall(r"^\s+def test_", text, re.M))


def score(task: str, folder: Path, timeout: int = 180) -> dict[str, Any]:
    """Run the hidden tests against the code in `folder` (never inside it: in a copy)."""
    total = count_hidden(task)
    with tempfile.TemporaryDirectory(prefix="rt-bench-score-") as tmp:
        work = Path(tmp) / "w"
        shutil.copytree(folder, work, ignore=shutil.ignore_patterns(".git", ".roundtable", "__pycache__", "_hidden"))
        hidden = work / "_hidden"
        hidden.mkdir()
        (hidden / "__init__.py").write_text("", encoding="utf-8")
        shutil.copy2(TASKS_DIR / task / "hidden" / "test_hidden.py", hidden / "test_hidden.py")
        (work / "_score.py").write_text(_RUNNER, encoding="utf-8")
        try:
            out = subprocess.run([sys.executable, "-I", "_score.py"], cwd=str(work), capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"passed": 0, "total": total, "failed": ["(the hidden tests timed out)"]}
        line = (out.stdout.strip().splitlines() or [""])[-1]
        try:
            data = json.loads(line)
        except ValueError:
            return {"passed": 0, "total": total, "failed": ["(could not run: " + (out.stderr.strip().splitlines() or ["?"])[-1][:200] + ")"]}
    failed = data["failed"]
    if any(f.startswith("_FailedTest") or "_FailedTest" in f for f in failed):
        return {"passed": 0, "total": total, "failed": ["(the code could not be imported: sheet.py is missing or broken)"]}
    return {"passed": max(0, data["run"] - len(failed)), "total": max(total, data["run"]), "failed": failed}


# ---------------------------------------------------------------- contenders

def _python() -> str:
    """The Python command the contenders should use: some computers have only python3."""
    return "python" if shutil.which("python") or not shutil.which("python3") else "python3"


def _test_command() -> str:
    return f"{_python()} -m unittest discover -s tests"


def _brief(task: str) -> str:
    """What both the lone AI and the team are told; the full specification is TASK.md in their folder."""
    first = task_text(task).strip().splitlines()[0]
    return (f"{first}\nThe full specification is in TASK.md in this project: read it all and follow it exactly; "
            f"hidden tests will check every rule in it. Write your own tests too ({_test_command()}).")


def _solo_prompt(task: str) -> str:
    return (_brief(task) + "\nYou work alone in this folder. Make your tests pass and commit your work with git. "
            "Nobody will answer questions: decide yourself, then finish.")


def _team_prompt(task: str) -> str:
    return (_brief(task) + "\nSplit the work into tasks with clear files; every task's test command should be: "
            + _test_command())


def solo_command(m: Member, folder: Path, prompt: str) -> list[str]:
    from . import launch
    from .config import toml_value

    if m.app == "claude-code":
        cmd = [launch._exe("claude"), "-p", prompt, "--output-format", "stream-json", "--verbose", "--model", m.model]
        if m.effort:
            cmd += ["--effort", m.effort]
        return cmd + ["--permission-mode", "acceptEdits", "--allowedTools", ",".join(SOLO_TOOLS)]
    cmd = [launch._exe("codex"), "exec", "--json", "-m", m.model, "-C", str(folder), "--skip-git-repo-check",
           "-c", f"sandbox_mode={toml_value('workspace-write')}"]
    if m.effort:
        cmd += ["-c", f"model_reasoning_effort={toml_value(m.effort)}"]
    return cmd + [prompt]


def run_solo(task: str, m: Member, folder: Path, minutes: float, log) -> dict[str, Any]:
    from . import runner

    prepare_repo(task, folder)
    cmd = solo_command(m, folder, _solo_prompt(task))
    started = time.time()
    tokens = 0
    kwargs: dict[str, Any] = {"cwd": str(folder), "env": runner.clean_env(os.environ), "stdin": subprocess.DEVNULL,
                              "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT}
    if os.name != "nt":
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    timed_out = False
    import threading

    timer = threading.Timer(minutes * 60, lambda: runner._kill(proc))
    timer.daemon = True
    timer.start()
    with open(folder.parent / f"{folder.name}.stream.jsonl", "wb") as fh:
        assert proc.stdout is not None
        for raw in proc.stdout:
            fh.write(raw)
            _items, facts = runner._parse_line(m.app, raw.decode("utf-8", errors="replace").strip(), str(folder))
            tokens += int(facts.get("tokens") or 0)
    proc.wait()
    timer.cancel()
    seconds = time.time() - started
    if seconds >= minutes * 60:
        timed_out = True
    log(f"  finished in {seconds / 60:.1f} min (exit {proc.returncode})")
    return {"seconds": round(seconds, 1), "tokens": tokens, "exit": proc.returncode, "timed_out": timed_out}


def _handle_for(m: Member, taken: set[str]) -> str:
    skip = {"claude", "gpt", "gemini", "code", "cli"}
    word = next((w for w in re.split(r"[-_.: ]+", m.model.lower()) if re.fullmatch(r"[a-z]{2,}", w) and w not in skip),
                "claude" if m.app == "claude-code" else "codex")
    name, i = word, 2
    while name in taken:
        name = f"{word}{i}"
        i += 1
    taken.add(name)
    return name


def run_team(task: str, members: list[Member], folder: Path, minutes: float, mode: str, review: str, log) -> dict[str, Any]:
    from . import dispatch, project, runner

    prepare_repo(task, folder)
    home, _lines = project.init_project(folder, name=f"bench-{task}")

    def H(op, **p):
        return dispatch.call(op, p, home=home, as_human=True, client="bench")

    taken: set[str] = set()
    handles = []
    for m in members:
        h = _handle_for(m, taken)
        H("seat.add", handle=h, model=m.model, app=m.app)
        if m.effort:
            H("seat.set", handle=h, effort=m.effort)
        handles.append(h)
    H("plan.goal", goal=_team_prompt(task), mode=mode, auto=True, review=review)
    started = time.time()
    for h in handles:
        runner.start_detached(home, h)
    log(f"  team {', '.join(handles)} started ({mode} planning, {review} checking)")
    outcome = "timed out"
    try:
        while time.time() - started < minutes * 60:
            time.sleep(5)
            stage = dispatch.call("plan.view", {}, home=home, as_human=True, client="bench").data.get("stage")
            if stage in ("done", "cancelled"):
                outcome = stage
                break
    finally:
        for h in handles:
            runner.request_stop(home, h)
    seconds = time.time() - started
    tokens = sum(int(runner.read_state(home, h).get("tokens") or 0) for h in handles)
    log(f"  plan {outcome} after {seconds / 60:.1f} min")
    return {"seconds": round(seconds, 1), "tokens": tokens, "outcome": outcome, "timed_out": outcome == "timed out", "seats": handles}


def run(task: str, contenders: list[Contender], out: Path, *, minutes: float = 40, mode: str = "quick", review: str = "mid",
        log=print) -> dict[str, Any]:
    task_text(task)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for i, c in enumerate(contenders, 1):
        folder = out / f"{i}-{'solo' if c.kind == 'solo' else 'team'}-{'-'.join(m.model for m in c.members)}"
        log(f"[{i}/{len(contenders)}] {c.label}")
        try:
            info = run_solo(task, c.members[0], folder, minutes, log) if c.kind == "solo" else \
                run_team(task, c.members, folder, minutes, mode, review, log)
        except RTError as exc:
            info = {"error": exc.message + (f" ({exc.hint})" if exc.hint else ""), "seconds": 0, "tokens": 0}
            log(f"  could not run: {info['error']}")
        sc = score(task, folder) if folder.exists() else {"passed": 0, "total": count_hidden(task), "failed": ["(nothing produced)"]}
        log(f"  hidden tests: {sc['passed']} of {sc['total']}")
        c.result = dict(info, **sc, folder=str(folder))
        results.append({"contender": c.label, "kind": c.kind, "members": [m.__dict__ for m in c.members], **c.result})
    report = {"task": task, "minutes_limit": minutes, "mode": mode, "review": review, "results": results,
              "at": time.strftime("%Y-%m-%d %H:%M")}
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "report.md").write_text(markdown(report), encoding="utf-8")
    return report


def markdown(report: dict) -> str:
    lines = [f"# Roundtable benchmark: {report['task']}", "",
             f"{report['at']} · time limit {report['minutes_limit']} min per contender · team planning: {report['mode']} · checking: {report['review']}", "",
             "| Contender | Hidden tests passed | Minutes | Tokens |", "| --- | --- | --- | --- |"]
    for r in report["results"]:
        pct = 100 * r["passed"] / r["total"] if r["total"] else 0
        note = " (stopped at the time limit)" if r.get("timed_out") else (" (error)" if r.get("error") else "")
        lines.append(f"| {r['contender']} | {r['passed']} of {r['total']} ({pct:.0f}%){note} | {r['seconds'] / 60:.1f} | {r['tokens']:,} |")
    lines += ["", "Tokens are what the apps reported; plan limits are shared by AIs from the same company.", ""]
    for r in report["results"]:
        if r["failed"]:
            lines.append(f"**{r['contender']}** failed: " + ", ".join(r["failed"][:30]) + (" …" if len(r["failed"]) > 30 else ""))
            lines.append("")
        if r.get("error"):
            lines.append(f"**{r['contender']}** could not run: {r['error']}")
            lines.append("")
    lines.append("Each contender's work is kept in its folder next to this report.")
    return "\n".join(lines) + "\n"


def contenders_from(solo: list[str] | None, team: list[str] | None) -> list[Contender]:
    out: list[Contender] = []
    for s in solo or []:
        out.append(Contender("solo", [parse_member(s)]))
    for t in team or []:
        members = [parse_member(x) for x in t.split(",") if x.strip()]
        if len(members) < 2:
            raise RTError(INVALID, "a team needs two or more members", "e.g. --team claude,codex")
        out.append(Contender("team", members))
    if not out:
        c, x = parse_member("claude"), parse_member("codex")
        out = [Contender("solo", [c]), Contender("solo", [x]), Contender("team", [parse_member("claude"), parse_member("codex")])]
    return out


def main(args) -> int:
    if args.sub == "list":
        for t in tasks():
            first = task_text(t).strip().splitlines()[0]
            print(f"{t}: {first[:100]} ({count_hidden(t)} hidden tests)")
        return 0
    if args.sub == "score":
        sc = score(args.task, Path(args.folder))
        print(f"{sc['passed']} of {sc['total']} hidden tests pass")
        for f in sc["failed"]:
            print(f"  failed: {f}")
        return 0 if sc["passed"] == sc["total"] else 1
    cs = contenders_from(args.solo, args.team)
    out = Path(args.out or (Path.cwd() / "roundtable-bench" / time.strftime("%Y%m%d-%H%M%S")))
    print(f"benchmark {args.task}: {len(cs)} contenders, up to {args.minutes} min each; work goes to {out}")
    print("this uses your real Claude Code / Codex limits.")
    report = run(args.task, cs, out, minutes=args.minutes, mode=args.mode, review=args.review)
    print()
    print(markdown(report))
    print(f"report: {out / 'report.md'}")
    return 0
