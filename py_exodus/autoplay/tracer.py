"""Live-run tracer: records autoplay sessions in rollout format (--trace).

Mirrors ``nn.rollout_recorder``'s row schema so any user-run autoplay can
be analyzed posthoc with the same tooling (``scripts/rollout_atlas.py``,
failure attributions), including runs that CRASH: the tracer captures a
stack trace end-row before the exception propagates.
"""
from __future__ import annotations

import gzip
import json
import time
import traceback
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from py_exodus.state_machine import StateMachine

from py_exodus.nn.rollout_recorder import (
    _nearby_threats,
    _party_snapshot,
)


class RunTracer:
    """Writes one gzipped JSONL per run; inert unless enabled."""

    def __init__(
        self,
        enabled: bool = False,
        seed: int | None = None,
        out_dir: Path | str | None = None,
    ) -> None:
        self.enabled = enabled
        self.seed = seed
        self._file: Any = None
        self._path: Path | None = None
        self._last_state: tuple | None = None
        self._prev_screen_kind = "OverworldScreen"
        self._combat_gold: int | None = None
        self._n_rows = 0
        if enabled:
            out = Path(out_dir) if out_dir else (
                Path(__file__).resolve().parent.parent / "nn" / "data" / "runtrace"
            )
            out.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            self._path = out / f"runtrace_seed{seed}_{stamp}.jsonl.gz"
            self._file = gzip.open(self._path, "wt", encoding="utf-8")
            self._emit({"t": "start", "seed": seed, "when": stamp})

    # -- recording ---------------------------------------------------------

    def _emit(self, row: dict[str, Any]) -> None:
        if self._file is None:
            return
        try:
            self._file.write(json.dumps(row) + "\n")
            self._file.flush()
            self._n_rows += 1
        except Exception:
            pass  # tracing must never break a run

    def record_step(self, state_machine: StateMachine, key: int | None) -> None:
        """Call once per autoplay tick (from AutoPlayController.step)."""
        if not self.enabled or self._file is None:
            return
        screen = state_machine.current_screen
        if screen is None:
            return
        party = getattr(screen, "party", None)
        screen_kind = type(screen).__name__

        # Combat boundaries (same schema as rollout_recorder v2)
        if screen_kind == "CombatScreen" and self._prev_screen_kind != "CombatScreen":
            self._emit({
                "t": "combat_start",
                "x": party.x if party else -1,
                "y": party.y if party else -1,
                "creatures": sorted(
                    {str(getattr(m, "tile", "")).lower() for m in getattr(getattr(screen, "arena", None), "monsters", ())}
                ),
                "monster_count": len(getattr(getattr(screen, "arena", None), "monsters", ())),
                "gold": party.gold if party else -1,
                **(_party_snapshot(party, screen) if party else {}),
            })
            self._combat_gold = party.gold if party else None
        elif screen_kind != "CombatScreen" and self._prev_screen_kind == "CombatScreen":
            self._emit({
                "t": "combat_end",
                "gold": party.gold if party else -1,
                "gold_delta": (party.gold - self._combat_gold)
                if (party and self._combat_gold is not None) else 0,
            })
            self._combat_gold = None
        self._prev_screen_kind = screen_kind

        # Location transitions with gold
        state_sig = (
            getattr(party, "x", -1),
            getattr(party, "y", -1),
            str(getattr(getattr(party, "transport", None), "value", "?")).lower(),
            screen_kind,
        )
        if state_sig != self._last_state:
            row = {
                "t": "s",
                "map": getattr(getattr(screen, "game_map", None), "id", getattr(party, "map_id", 0)),
                "x": getattr(party, "x", -1),
                "y": getattr(party, "y", -1),
                "goal": "",
                "key": key,
                **(_party_snapshot(party, screen) if party else {}),
                **(_nearby_threats(screen) if party else {}),
            }
            try:
                from py_exodus.autoplay.planner import evaluate_goal

                if party is not None:
                    row["goal"] = evaluate_goal(
                        party, map_id=row["map"]
                    ).name
            except Exception:
                pass
            self._emit(row)
            self._last_state = state_sig

    def end(self, outcome: str, exc: BaseException | None = None) -> None:
        """Write the end row (with a stack trace on crashes) and close."""
        if self._file is None:
            return
        row: dict[str, Any] = {"t": "end", "seed": self.seed, "outcome": outcome}
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

    @property
    def path(self) -> Path | None:
        return self._path
