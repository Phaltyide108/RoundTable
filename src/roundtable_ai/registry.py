"""The operation registry: one place that defines every action.

Each operation is a plain function `handler(ctx, **params) -> Result`,
registered with @op. The MCP server builds its 8 tools from the registry
(tool + action), and the CLI builds its commands from it too, so a model and
a human always get the same behavior and the same messages.

Param types: str, int, bool, list (of str), objects (list of dicts), object (dict).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .errors import INVALID, RTError

SEAT = "seat"      # only a seat (a model) may call
HUMAN = "human"    # only the human (CLI / dashboard) may call
ANY = "any"        # either


@dataclass
class Param:
    name: str
    type: str = "str"            # str | int | bool | list | objects | object
    required: bool = False
    desc: str = ""
    enum: tuple[str, ...] | None = None
    default: Any = None


@dataclass
class Op:
    name: str                     # 'task.claim'
    func: Callable[..., "Result"]
    params: list[Param]
    who: str = SEAT
    desc: str = ""
    tool: str | None = None       # MCP tool name, e.g. 'rt_task'; None = not exposed to seats
    action: str | None = None     # action within the tool, e.g. 'claim'
    frozen_ok: bool = False       # allowed while work is stopped (freeze / unacked level-5)
    housekeeping: bool = True     # run lease expiry/renewal before the call


@dataclass
class Result:
    text: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": True, "text": self.text, "data": self.data}


OPS: dict[str, Op] = {}


def op(
    name: str,
    *,
    params: list[Param] | tuple[Param, ...] = (),
    who: str = SEAT,
    desc: str = "",
    tool: str | None = None,
    action: str | None = None,
    frozen_ok: bool = False,
    housekeeping: bool = True,
):
    def deco(func: Callable[..., Result]) -> Callable[..., Result]:
        if name in OPS:
            raise RuntimeError(f"operation {name} registered twice")
        OPS[name] = Op(
            name=name, func=func, params=list(params), who=who, desc=desc,
            tool=tool, action=action, frozen_ok=frozen_ok, housekeeping=housekeeping,
        )
        return func

    return deco


def coerce_params(o: Op, raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and convert incoming params (from JSON or the command line).

    Unknown params are refused (catches typos like 'tsk'). Missing optional
    params get their default.
    """
    import json

    known = {p.name: p for p in o.params}
    unknown = [k for k in raw if k not in known]
    if unknown:
        allowed = ", ".join(known) or "none"
        raise RTError(INVALID, f"{o.name}: unknown parameter(s) {', '.join(unknown)}", f"allowed: {allowed}")
    out: dict[str, Any] = {}
    for p in o.params:
        if p.name not in raw or raw[p.name] is None:
            if p.required:
                raise RTError(INVALID, f"{o.name}: missing required parameter '{p.name}'", p.desc or None)
            out[p.name] = p.default
            continue
        v = raw[p.name]
        try:
            if p.type == "str":
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    v = str(v)
                if not isinstance(v, str):
                    raise ValueError("text")
            elif p.type == "int":
                if isinstance(v, bool):
                    raise ValueError("number")
                v = int(v)
            elif p.type == "bool":
                if isinstance(v, str):
                    if v.lower() in ("true", "yes", "1", "on"):
                        v = True
                    elif v.lower() in ("false", "no", "0", "off"):
                        v = False
                    else:
                        raise ValueError("true/false")
                elif not isinstance(v, bool):
                    raise ValueError("true/false")
            elif p.type == "list":
                if isinstance(v, str):
                    s = v.strip()
                    v = json.loads(s) if s.startswith("[") else [x.strip() for x in s.split(",") if x.strip()]
                if not isinstance(v, list):
                    raise ValueError("list")
                v = [str(x) if not isinstance(x, str) else x for x in v]
            elif p.type == "objects":
                if isinstance(v, str):
                    v = json.loads(v)
                if isinstance(v, dict):
                    v = [v]
                if not isinstance(v, list) or not all(isinstance(x, dict) for x in v):
                    raise ValueError("list of objects")
            elif p.type == "object":
                if isinstance(v, str):
                    v = json.loads(v)
                if not isinstance(v, dict):
                    raise ValueError("object")
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            kind = exc.args[0] if exc.args and isinstance(exc.args[0], str) and len(exc.args[0]) < 20 else p.type
            raise RTError(INVALID, f"{o.name}: parameter '{p.name}' must be {kind}") from None
        if p.enum and v not in p.enum:
            raise RTError(INVALID, f"{o.name}: '{p.name}' must be one of {', '.join(p.enum)} (got {v!r})")
        out[p.name] = v
    return out


def tools() -> dict[str, list[Op]]:
    """MCP tool name -> its actions (ops), in registration order."""
    out: dict[str, list[Op]] = {}
    for o in OPS.values():
        if o.tool:
            out.setdefault(o.tool, []).append(o)
    return out


def load_all() -> None:
    """Import every module that registers operations."""
    import importlib

    for mod in MODULES:
        importlib.import_module(f"roundtable_ai.{mod}")


# Modules that register operations (imported by load_all). Keep in sync with DESIGN.md.
MODULES = (
    "seats",
    "sync",
    "tasks",
    "leases",
    "plans",
    "reviews",
    "suggestions",
    "alerts",
    "votes",
    "admin",
    "usage",
    "memory",
    "council",
)
