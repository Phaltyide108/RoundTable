"""Regenerate docs/cli.md and docs/mcp-tools.md from the code.

Run after adding or changing an operation or a command:
    python scripts/gen_docs.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from roundtable_ai import cli, mcp_server, registry  # noqa: E402

TYPES = {"str": "text", "int": "number", "bool": "true/false", "list": "list of text", "objects": "list of objects", "object": "object"}


def mcp_doc() -> str:
    tools, index = mcp_server.build_tools()
    out = [
        "# MCP tools reference",
        "",
        "Roundtable gives every seat these 8 tools. Every tool also accepts `key` (the seat key from joining; not needed when the "
        "session is bound to a seat) and `format` (`text` or `json`). Each reply starts with the seat's inbox line, e.g. "
        "`[rt: 2 new · 1 review for you]`.",
        "",
        "This page is generated from the code by `scripts/gen_docs.py`.",
        "",
    ]
    for t in tools:
        name = t["name"]
        out += [f"## {name}", "", mcp_server.TOOL_INFO[name], ""]
        if name == "rt_sync":
            out += ["First call in a new chat: `rt_sync join=\"<seat>\"` returns your key and the rules.", ""]
        out += ["| Action | Parameters | What it does |", "| --- | --- | --- |"]
        for (tool, action), o in index.items():
            if tool != name:
                continue
            ps = []
            for p in o.params:
                bit = f"`{p.name}`" + ("" if p.required else " (optional)") + f" {TYPES[p.type]}"
                if p.enum:
                    bit += ": " + " / ".join(p.enum)
                ps.append(bit)
            out.append(f"| `{action}` | {'<br>'.join(ps) or 'none'} | {o.desc} |")
        out.append("")
    return "\n".join(out)


def cli_doc() -> str:
    parser = cli.build_parser()
    out = ["# Command reference", "", "Generated from the code by `scripts/gen_docs.py`. Every command also accepts the global options below.", "",
           "```text", parser.format_help().strip(), "```", ""]
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    for name, p in sub.choices.items():
        out += [f"## rt {name}", "", "```text", p.format_help().strip(), "```", ""]
        inner = [a for a in p._actions if isinstance(a, argparse._SubParsersAction)]
        for s in inner:
            for sname, sp in s.choices.items():
                out += [f"### rt {name} {sname}", "", "```text", sp.format_help().strip(), "```", ""]
    human = sorted(o.name for o in registry.OPS.values() if o.who == registry.HUMAN)
    out += ["## Any operation: rt call", "", "`rt call <operation> key=value ...` runs any operation directly. Human operations:", ""]
    out += [f"- `{n}`: {registry.OPS[n].desc}" for n in human]
    return "\n".join(out) + "\n"


def main() -> int:
    registry.load_all()
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "mcp-tools.md").write_text(mcp_doc() + "\n", encoding="utf-8")
    (docs / "cli.md").write_text(cli_doc(), encoding="utf-8")
    print("wrote docs/mcp-tools.md and docs/cli.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
