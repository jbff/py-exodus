"""Symbolic-rollout recorder for NN strategy training (hazard critic et al.).

Drives the symbolic AutoPlayController through full episodes on TRAIN
seeds (0-899) and records a compact JSONL per seed:

* per-step rows (deduplicated: only when position/transport/goal changed
  or an event fired) with party + world context features for the hazard
  critic: map, position, transport, goal, party hp/lv/marks/weapons,
  gold, food, ship hull, nearby creature tiles and distances
* event rows: combat start/end (creature, win/lose), member death,
  party wipe, hull drop, food/gold milestones, episode end

Downstream training consumes these; the recorder must be seed-reproducible
(same party setup as hybrid_eval) and never touch holdout seeds 900-999.
"""
from __future__ import annotations

import gzip
import json
import logging
import random
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

from py_exodus.constants import Profession, Race  # for _PARTY_SETUP below

TRAIN_SEED_MAX = 899

#: Party setup mirror of hybrid_eval._eval_one_seed (canonical autoplay run).
_PARTY_SETUP = [
    # (name, sex, race, profession, strength, dexterity, intelligence, wisdom)
    ("SHADOW", "M", Race.ELF, Profession.THIEF, 15, 25, 10, 10),
    ("GRUMM", "M", Race.DWARF, Profession.FIGHTER, 25, 15, 10, 10),
    ("SERENA", "F", Race.BOBIT, Profession.CLERIC, 15, 15, 10, 25),
    ("ZIRCON", "M", Race.FUZZY, Profession.WIZARD, 15, 15, 25, 10),
]


def _party_snapshot(party, screen) -> dict[str, Any]:
    living = [m for m in party.members if not m.is_dead()]
    return {
        "hp": [m.hp for m in party.members],
        "min_hp_frac": min(
            (m.hp / max(1, m.max_hp) for m in living), default=0.0
        ),
        "levels": [m.level for m in party.members],
        "marks": [[m.marks[0], m.marks[1], m.marks[2], m.marks[3]] for m in party.members],
        "gold": party.gold,
        "food": min(m.food for m in living) if living else 0,
        "transport": party.transport.value.lower(),
        "hull": getattr(party, "ship_hull", None),
        "living": len(living),
    }


def _nearby_threats(screen) -> dict[str, Any]:
    """Nearest creature tiles around the party (overworld context only)."""
    party = getattr(screen, "party", None)
    if party is None:
        return {}
    px, py = party.x, party.y
    best: dict[str, int] = {}
    for c in getattr(screen, "creatures", ()) or ():
        tile = str(c.get("tile_name") or c.get("tile") or "")
        if tile in ("", "whirlpool"):
            continue
        if "x" not in c or "y" not in c:
            continue
        d = abs(c["x"] - px) + abs(c["y"] - py)
        prev = best.get(tile, 10**9)
        if d < prev:
            best[tile] = d
    return {"nearby": {k: v for k, v in sorted(best.items(), key=lambda kv: kv[1])[:4]}}


def record_rollout(
    seed: int,
    out_path: Path | str,
    *,
    max_steps: int = 160_000,
    assets_dir: str = "data",
    nn_combat: bool = False,
    nn_device: str = "auto",
    step_cb: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Record one autoplay episode to ``out_path`` (gzipped JSONL).

    ``nn_combat`` must mirror how the run being studied drives combat:
    live ``--autoplay`` sets it TRUE (``__main__``: nn_combat defaults to
    the --autoplay flag), so a corpus intended to describe live Autoplay
    has to record with it. The default stays False so historical
    symbolic-combat corpora remain reproducible."""
    import pygame
    import torch

    from py_exodus.assets import AssetManager
    from py_exodus.entities.character import Character
    from py_exodus.entities.party import Party
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.autoplay.controller import AutoPlayController
    from py_exodus.state_machine import StateMachine

    if not (0 <= seed <= TRAIN_SEED_MAX):
        raise ValueError(f"seed {seed} outside training range 0..{TRAIN_SEED_MAX}")

    torch.set_num_threads(1)

    am = AssetManager(assets_dir)
    am.load_all()
    random.seed(seed)

    from py_exodus.constants import Profession, Race  # noqa: F401 (used in setup)

    party = Party()
    for name, sex, race, prof, s, d, i, w in _PARTY_SETUP:
        party.add_member(
            Character(name, sex, race, prof, strength=s, dexterity=d, intelligence=i, wisdom=w, gold=150)
        )
    party.x, party.y = 44, 20

    sm = StateMachine(asset_mgr=am, audio=None)
    sm.set_screen(OverworldScreen(party=party, asset_mgr=am))

    from py_exodus.autoplay.planner import evaluate_goal

    ctrl = AutoPlayController(
        enabled=True, nn_combat=nn_combat, nn_device=nn_device
    )

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    last_state: tuple | None = None
    events = 0

    outcome = "SURVIVED"
    gzip_ctx = gzip.open(out_path, "wt", encoding="utf-8") if str(out_path).endswith(".gz") else open(out_path, "w", encoding="utf-8")
    try:
        with gzip_ctx as f:
            for step in range(max_steps):
                scr = sm.current_screen
                if party.is_party_dead():
                    outcome = f"WIPED@{step}"
                    break
                if getattr(party, "exodus_defeated", 0) > 0:
                    outcome = f"WON@{step}"
                    break

                state_sig = (
                    party.x, party.y, party.transport.value.lower(),
                    type(scr).__name__,
                )
                if state_sig != last_state:
                    row = {
                        "t": "s",
                        "step": step,
                        "seed": seed,
                        "map": getattr(getattr(scr, "game_map", None), "id", getattr(party, "map_id", 0)),
                        "x": party.x,
                        "y": party.y,
                        "goal": evaluate_goal(party, map_id=getattr(getattr(scr, "game_map", None), "id", getattr(party, "map_id", 0))).name,
                        **_party_snapshot(party, scr),
                        **_nearby_threats(scr),
                    }
                    f.write(json.dumps(row) + "\n")
                    if step_cb:
                        step_cb(row)
                    last_state = state_sig
                ctrl.step(sm)
                sm.update(0.05)
            else:
                outcome = "STEP_CAP"
            # End row goes through the SAME stream — appending plain text
            # to a gzipped file afterwards corrupts the archive tail.
            f.write(json.dumps({
                "t": "end",
                "seed": seed,
                "outcome": outcome,
                "result": {
                    "gold": party.gold,
                    "levels": [m.level for m in party.members],
                    "map": getattr(party, "map_id", 0),
                },
            }) + "\n")
    finally:
        pass
    return {"seed": seed, "outcome": outcome}


def record_many(
    seeds: list[int],
    out_dir: Path | str,
    *,
    max_steps: int = 160_000,
    nn_combat: bool = False,
    nn_device: str = "auto",
) -> list[dict[str, Any]]:
    """Record a batch of seeds (single process; use the CLI for parallelism)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for seed in seeds:
        out = out_dir / f"rollout_{seed}.jsonl.gz"
        if out.exists():
            continue
        res = record_rollout(
            seed, out, max_steps=max_steps, nn_combat=nn_combat, nn_device=nn_device
        )
        logger.info("seed %s -> %s", seed, res["outcome"])
        results.append(res)
    return results


if __name__ == "__main__":
    import argparse
    import multiprocessing as mp

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", type=int, nargs="+", required=True)
    ap.add_argument("--out-dir", default="py_exodus/nn/data/rollouts")
    ap.add_argument("--max-steps", type=int, default=160_000)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument(
        "--nn-combat",
        action="store_true",
        help="Drive combat with the NN policy (matches live --autoplay).",
    )
    ap.add_argument("--nn-device", default="auto", choices=("auto", "cuda", "cpu"))
    args = ap.parse_args()

    def _work(seed: int) -> dict[str, Any]:
        if not (0 <= seed <= TRAIN_SEED_MAX):
            raise ValueError(f"seed {seed} outside 0..{TRAIN_SEED_MAX}")
        out = Path(args.out_dir) / f"rollout_{seed}.jsonl.gz"
        return record_rollout(
            seed,
            out,
            max_steps=args.max_steps,
            nn_combat=args.nn_combat,
            nn_device=args.nn_device,
        )

    with mp.get_context("fork").Pool(args.workers) as pool:
        for res in pool.map(_work, args.seeds):
            print(res)
