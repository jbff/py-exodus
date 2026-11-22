"""Autoplay run tracer: one gzipped JSONL per run, for post-mortem analysis.

Used by the live game (``--trace``) and by the headless batch runner
(``python -m py_exodus.autoplay.batch``), so both produce the same schema and
``scripts/autoplay_atlas.py`` reads either.

Row types (``"t"`` field):

* ``start``         seed, wall-clock stamp
* ``s``             state row, written whenever position / transport / screen /
                    goal changes: step, map, x, y, goal, key, party snapshot,
                    nearby creatures
* ``combat_start``  creatures, monster count, party snapshot
* ``combat_end``    gold delta, party snapshot
* ``end``           outcome (``WON@n`` / ``WIPED@n`` / ``STEP_CAP@n`` / ``QUIT@n``
                    / ``CRASHED@n``), final snapshot, traceback on crashes

Tracing must never break a run: every write is best-effort.
"""
from __future__ import annotations

import gzip
import json
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any

from py_exodus.constants import ArmorType, Status, WeaponType

if TYPE_CHECKING:
    from py_exodus.state_machine import StateMachine

DEFAULT_TRACE_DIR = Path("traces")


def _status_code(m) -> str:
    st = getattr(m, "status", Status.GOOD)
    return {
        Status.GOOD: "G",
        Status.POISONED: "P",
        Status.DEAD: "D",
        Status.ASH: "A",
    }.get(st, str(getattr(st, "value", st))[:1])


def party_snapshot(party) -> dict[str, Any]:
    """Compact per-member + party-wide state used by every trace row."""
    members = list(getattr(party, "members", ()) or ())
    living = [m for m in members if not m.is_dead()]
    return {
        "hp": [m.hp for m in members],
        "mhp": [m.max_hp for m in members],
        "mp": [m.mp for m in members],
        "st": "".join(_status_code(m) for m in members),
        "lv": [m.level for m in members],
        "food": [m.food for m in members],
        "gold": party.gold,
        "marks": "".join(
            "KFSO"[i] if any(m.marks[i] > 0 for m in members) else "-" for i in range(4)
        ),
        "cards": "".join(
            "DSML"[i] if any(m.cards[i] > 0 for m in members) else "-" for i in range(4)
        ),
        "exo": sum(
            1
            for m in members
            if (m.weapon == WeaponType.EXOTIC or m.weapons.get(WeaponType.EXOTIC, 0) > 0)
        )
        + sum(
            1
            for m in members
            if (m.armor == ArmorType.EXOTIC or m.armors.get(ArmorType.EXOTIC, 0) > 0)
        ),
        "keys": sum(m.keys for m in living),
        "transport": str(getattr(getattr(party, "transport", None), "value", "?")).lower(),
        "hull": getattr(party, "ship_hull", None),
        "living": len(living),
    }


def nearby_creatures(screen, party, radius: int = 8) -> dict[str, int]:
    """Nearest distance per overworld creature tile within ``radius``."""
    px, py = getattr(party, "x", 0), getattr(party, "y", 0)
    best: dict[str, int] = {}
    for c in getattr(screen, "creatures", ()) or ():
        tile = str(c.get("tile_name") or c.get("tile") or "").lower()
        if not tile or "x" not in c or "y" not in c:
            continue
        d = abs(c["x"] - px) + abs(c["y"] - py)
        if d <= radius and d < best.get(tile, 10**9):
            best[tile] = d
    return dict(sorted(best.items(), key=lambda kv: kv[1])[:5])


def _screen_map(screen, party) -> Any:
    gm = getattr(screen, "game_map", None)
    mid = getattr(gm, "id", None)
    if mid is None:
        dm = getattr(screen, "dungeon_map", None) or getattr(getattr(screen, "state", None), "dmap", None)
        mid = getattr(dm, "id", None)
    return mid if mid is not None else getattr(party, "map_id", 0)


class RunTracer:
    """Writes one gzipped JSONL per run; inert until activated."""

    def __init__(
        self,
        enabled: bool = False,
        seed: int | None = None,
        out_dir: Path | str | None = None,
        out_path: Path | str | None = None,
    ) -> None:
        self.seed = seed
        self.out_dir = Path(out_dir) if out_dir else DEFAULT_TRACE_DIR
        self._fixed_path = Path(out_path) if out_path else None
        self.enabled = False
        self.steps = 0
        self._file: Any = None
        self._path: Path | None = None
        self._last_sig: tuple | None = None
        self._prev_screen = ""
        self._combat_gold: int | None = None
        if enabled:
            self.activate()

    @property
    def path(self) -> Path | None:
        return self._path

    def activate(self) -> None:
        """Start tracing (F9-toggled autoplay begins after launch)."""
        self.enabled = True
        if self._file is not None:
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        if self._fixed_path is not None:
            self._path = self._fixed_path
        else:
            tag = f"seed{self.seed}_" if self.seed is not None else ""
            self._path = self.out_dir / f"trace_{tag}{stamp}.jsonl.gz"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = gzip.open(self._path, "wt", encoding="utf-8")
        self._emit({"t": "start", "seed": self.seed, "when": stamp})

    def _emit(self, row: dict[str, Any]) -> None:
        if self._file is None:
            return
        try:
            self._file.write(json.dumps(row, separators=(",", ":")) + "\n")
        except Exception:
            pass

    def record_step(
        self, state_machine: StateMachine, key: int | None, goal: Any = None, why: str | None = None
    ) -> None:
        """Call once per autoplay step, after the step's key was emitted."""
        if not self.enabled or self._file is None:
            return
        self.steps += 1
        screen = state_machine.current_screen
        if screen is None:
            return
        party = getattr(screen, "party", None)
        if party is None or not getattr(party, "members", None):
            return
        kind = type(screen).__name__

        if kind == "CombatScreen" and self._prev_screen != "CombatScreen":
            arena = getattr(screen, "arena", None)
            mons = list(getattr(arena, "monsters", ()) or ())
            self._emit({
                "t": "combat_start",
                "step": self.steps,
                "map": _screen_map(screen, party),
                "x": party.x,
                "y": party.y,
                "creatures": sorted({str(getattr(m, "tile", getattr(m, "name", ""))).lower() for m in mons}),
                "n": len(mons),
                **party_snapshot(party),
            })
            self._combat_gold = party.gold
        elif kind != "CombatScreen" and self._prev_screen == "CombatScreen":
            self._emit({
                "t": "combat_end",
                "step": self.steps,
                "gold_delta": party.gold - (self._combat_gold or party.gold),
                **party_snapshot(party),
            })
            self._combat_gold = None
        self._prev_screen = kind
        if kind == "CombatScreen":
            return

        if goal is None:
            try:
                from py_exodus.autoplay.planner import evaluate_goal

                goal = evaluate_goal(party, map_id=_screen_map(screen, party))
            except Exception:
                goal = None
        goal_name = getattr(goal, "name", None) if goal is not None else None
        if kind in ("TownScreen",) and hasattr(screen, "avatar_x"):
            x, y = screen.avatar_x, screen.avatar_y
        elif kind == "DungeonScreen":
            st = getattr(screen, "state", None)
            x, y = getattr(st, "x", -1), getattr(st, "y", -1)
        else:
            x, y = party.x, party.y
        z = getattr(getattr(screen, "state", None), "z", None) if kind == "DungeonScreen" else None
        sig = (kind, _screen_map(screen, party), x, y, z, str(party.transport), goal_name)
        if sig == self._last_sig:
            return
        self._last_sig = sig
        row: dict[str, Any] = {
            "t": "s",
            "step": self.steps,
            "scr": kind.replace("Screen", ""),
            "map": sig[1],
            "x": x,
            "y": y,
            "goal": goal_name,
            "key": key,
            **party_snapshot(party),
        }
        if z is not None:
            row["z"] = z
        if why:
            row["why"] = why
        if kind == "OverworldScreen":
            row["near"] = nearby_creatures(screen, party)
        elif kind == "TownScreen":
            gm = getattr(screen, "game_map", None)
            row["people"] = [
                [n.x, n.y, str(getattr(n, "tile_name", ""))[:3], str(getattr(n, "movement", ""))[:1]]
                for n in (getattr(gm, "npcs", ()) or ())
                if abs(n.x - x) <= 4 and abs(n.y - y) <= 4
            ]
        self._emit(row)

    def end(self, outcome: str, party=None, exc: BaseException | None = None) -> None:
        """Write the end row (with a traceback on crashes) and close."""
        if self._file is None:
            return
        row: dict[str, Any] = {"t": "end", "seed": self.seed, "outcome": f"{outcome}@{self.steps}"}
        if party is not None and getattr(party, "members", None):
            row.update(party_snapshot(party))
        if exc is not None:
            row["traceback"] = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )[-4000:]
        self._emit(row)
        try:
            self._file.close()
        except Exception:
            pass
        self._file = None
        self.enabled = False
