"""The context every operation receives: who is acting, on which project."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config as config_mod
from .db import Store
from .paths import config_path, db_path, find_home, project_root, resolve_home_arg

HUMAN = "human"
SYSTEM = "system"


@dataclass
class Ctx:
    home: Path                 # .../project/.roundtable
    root: Path                 # .../project
    db: Store
    cfg: config_mod.Config
    actor: str = HUMAN         # seat handle, 'human' or 'system'
    client: str = "cli"        # cli | mcp | watch | dashboard | proofrun | hook | test
    notes: list[str] = field(default_factory=list)  # extra lines handlers want appended to the reply

    @property
    def is_human(self) -> bool:
        return self.actor == HUMAN

    @property
    def is_seat(self) -> bool:
        return self.actor not in (HUMAN, SYSTEM)

    def tx(self):
        return self.db.tx()

    def setting(self, section: str, key: str) -> Any:
        return self.cfg.get(section, key)

    def close(self) -> None:
        self.db.close()


def open_ctx(home: str | Path | None = None, actor: str = HUMAN, client: str = "cli") -> Ctx:
    h = resolve_home_arg(home) if home else find_home()
    store = Store.open(db_path(h))
    cfg = config_mod.load(config_path(h))
    return Ctx(home=h, root=project_root(h), db=store, cfg=cfg, actor=actor, client=client)


def with_actor(ctx: Ctx, actor: str, client: str | None = None) -> Ctx:
    """Same project/connection, different actor (e.g. a system follow-up)."""
    return Ctx(home=ctx.home, root=ctx.root, db=ctx.db, cfg=ctx.cfg, actor=actor, client=client or ctx.client)
