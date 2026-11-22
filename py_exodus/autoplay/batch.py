"""Headless autoplay batch runner: many seeds, one trace per seed.

    uv run python -m py_exodus.autoplay.batch --seeds 0-99 --workers 2 --out-dir traces/baseline

Each seed starts a fresh canonical party (Thief / Fighter / Cleric / Wizard) at
Castle British's gate and drives the REAL StateMachine through the same loop
``GameApp.run`` uses — ``autoplay.update(dt)`` then ``state_machine.update(dt)``
at 60 FPS — minus rendering and the pygame event pump. Combat is the same
symbolic auto-combat the live game uses, so a batch result describes what the
user would see with ``--autoplay`` (live play runs on wall-clock time, so only
batches are seed-reproducible).

Outputs ``<out-dir>/trace_<seed>.jsonl.gz`` (see ``autoplay.tracer``) plus a
one-line summary per seed on stdout. Analyze with ``scripts/autoplay_atlas.py``.
"""
from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import argparse
import random
import time
from pathlib import Path
from typing import Any

FRAME_DT = 1.0 / 60.0

#: Canonical autoplay party: (name, sex, race, profession, str, dex, int, wis).
# The one party autoplay is tested and tuned with (README), shared with
# scripts/reset_new_game.py so batches and live runs start alike. 50 points
# each, LairWare's creation budget (UltimaMacIF.c:2373); the batches used
# 60-point characters until 2026-11-22.
PARTY_SETUP = (
    ("SHADOW", "M", "ELF", "THIEF", 15, 25, 5, 5),
    ("GRUMM", "M", "DWARF", "FIGHTER", 25, 15, 5, 5),
    ("SERENA", "F", "BOBBIT", "CLERIC", 15, 5, 5, 25),
    ("ZIRCON", "M", "FUZZY", "WIZARD", 15, 5, 25, 5),
)

_ASSETS = None


def _assets():
    global _ASSETS
    if _ASSETS is None:
        from py_exodus.assets import AssetManager

        am = AssetManager(assets_dir=Path("assets"))
        am.load_tiles()
        am.load_xml_definitions()
        _ASSETS = am
    return _ASSETS


def build_party():
    from py_exodus.constants import Profession, Race, Sex
    from py_exodus.entities.character import Character
    from py_exodus.entities.party import Party

    party = Party()
    for name, sex, race, prof, s, d, i, w in PARTY_SETUP:
        party.add_member(
            Character(
                name,
                Sex.MALE if sex == "M" else Sex.FEMALE,
                Race[race],
                Profession[prof],
                strength=s,
                dexterity=d,
                intelligence=i,
                wisdom=w,
                gold=150,
            )
        )
    party.x, party.y = 44, 20
    return party


def _seed_dungeon_rngs() -> None:
    """Dungeon states build their own ``random.Random()`` (world/dungeon.py);
    derive each from the seeded global stream so a batch seed reproduces."""
    import types

    from py_exodus.world import dungeon

    if getattr(dungeon.random, "_autoplay_seeded", False):
        return
    real = dungeon.random
    proxy = types.ModuleType("random")
    proxy.__dict__.update(real.__dict__)
    proxy.Random = lambda *a, **k: real.Random(*a, **k) if (a or k) else real.Random(real.getrandbits(64))
    proxy._autoplay_seeded = True
    dungeon.random = proxy


def run_seed(
    seed: int,
    out_dir: Path | str,
    max_steps: int = 200_000,
    step_interval: float = 0.08,
) -> dict[str, Any]:
    """Play one seed to WON / WIPED / STEP_CAP and write its trace."""
    import pygame

    pygame.init()
    if not pygame.font.get_init():
        pygame.font.init()

    from py_exodus.autoplay.controller import AutoPlayController
    from py_exodus.autoplay.tracer import RunTracer
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.state_machine import StateMachine

    am = _assets()
    random.seed(seed)
    # tile_effects keeps its own unseeded die (swamp/lava rolls); seed it so a
    # batch seed reproduces. Dungeons still make their own random.Random().
    from py_exodus.world import tile_effects

    tile_effects._rng.seed(seed)
    _seed_dungeon_rngs()
    party = build_party()
    sm = StateMachine(asset_mgr=am, audio=None)
    sm.set_screen(OverworldScreen(party=party, asset_mgr=am))

    out = Path(out_dir) / f"trace_{seed}.jsonl.gz"
    tracer = RunTracer(enabled=True, seed=seed, out_path=out)
    ctrl = AutoPlayController(enabled=True, step_interval=step_interval, tracer=tracer)
    sm.autoplay_enabled = True

    t0 = time.monotonic()
    outcome = "STEP_CAP"
    try:
        while tracer.steps < max_steps:
            ctrl.update(FRAME_DT, sm)
            sm.update(FRAME_DT)
            if getattr(party, "exodus_defeated", 0) > 0 or getattr(party, "exodus_cards_status", 0) == 0xF:
                outcome = "WON"
                break
            if party.is_party_dead():
                outcome = "WIPED"
                break
            if not ctrl.enabled:
                outcome = "STOPPED"
                break
        tracer.end(outcome, party=party)
    except Exception as exc:  # keep the batch alive; the trace holds the traceback
        outcome = "CRASHED"
        tracer.end(outcome, party=party, exc=exc)
    living = [m for m in party.members if not m.is_dead()]
    return {
        "seed": seed,
        "outcome": f"{outcome}@{tracer.steps}",
        "secs": round(time.monotonic() - t0, 1),
        "lv": [m.level for m in party.members],
        "gold": party.gold,
        "living": len(living),
    }


def _parse_seeds(specs: list[str]) -> list[int]:
    seeds: list[int] = []
    for spec in specs:
        for part in spec.split(","):
            if "-" in part:
                a, b = part.split("-", 1)
                seeds.extend(range(int(a), int(b) + 1))
            elif part:
                seeds.append(int(part))
    return seeds


def main(argv: list[str] | None = None) -> int:
    import multiprocessing as mp

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", nargs="+", required=True, help="e.g. 0-99 or 1,5,9 or 3 7 11")
    ap.add_argument("--out-dir", default="traces/batch")
    ap.add_argument("--max-steps", type=int, default=200_000, help="autoplay steps (keys), combat included")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--step-interval", type=float, default=0.08, help="autoplay seconds per step (live default 0.08)")
    args = ap.parse_args(argv)

    seeds = _parse_seeds(args.seeds)
    Path(args.out_dir).mkdir(parents=True, exist_ok=True)

    def _job(seed: int) -> dict[str, Any]:
        return run_seed(seed, args.out_dir, max_steps=args.max_steps, step_interval=args.step_interval)

    if args.workers <= 1:
        for s in seeds:
            print(_job(s), flush=True)
        return 0
    with mp.get_context("fork").Pool(args.workers, maxtasksperchild=1) as pool:
        for res in pool.imap_unordered(_job_wrapper, [(s, args) for s in seeds]):
            print(res, flush=True)
    return 0


def _job_wrapper(packed) -> dict[str, Any]:
    seed, args = packed
    return run_seed(seed, args.out_dir, max_steps=args.max_steps, step_interval=args.step_interval)


if __name__ == "__main__":
    raise SystemExit(main())
