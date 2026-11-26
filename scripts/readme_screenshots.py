"""Render the README screenshots into docs/screenshots/ (headless).

    uv run python scripts/readme_screenshots.py [--seed 1]

- intro.png: the intro during the duel, under the title art.
- view.png: the View, LairWare's demo strip under the title.
- menu.png: the main menu.
- sosaria.png and dungeon.png: frames from a headless Full Autoplay run of
  the batch party (autoplay/batch.py). Each is the first frame at or after
  ``--sosaria-frame`` / ``--dungeon-frame`` on that screen. Batch seeds
  don't always replay exactly, so a rerun may pick a different moment.
  The panel is drawn with autoplay shown off, as a player would see it.

Saves go to a throwaway folder; the player's saves are never touched.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import tempfile
from pathlib import Path

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PY_EXODUS_SAVE_DIR"] = tempfile.mkdtemp(prefix="py-exodus-shots-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame  # noqa: E402

SIZE = (960, 600)
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"


def _intro_frame(am, view_only: bool, seconds: float) -> pygame.Surface:
    from py_exodus.screens.intro import IntroScreen

    screen = IntroScreen(asset_mgr=am, audio=None, view_only=view_only)
    surf = pygame.Surface(SIZE)
    for _ in range(int(seconds * 60)):
        screen.render(surf)
        screen.update(1 / 60)
    screen.render(surf)
    return surf


def _menu(am) -> pygame.Surface:
    from py_exodus.screens.start import StartScreen

    surf = pygame.Surface(SIZE)
    StartScreen(asset_mgr=am, audio=None, party=None, manager=None).render(surf)
    return surf


def _play(am, seed: int, wants: dict[str, int]) -> dict[str, pygame.Surface]:
    """Run autoplay; capture each wanted screen class at or after its frame."""
    from py_exodus.autoplay import batch
    from py_exodus.autoplay.controller import AutoPlayController
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.state_machine import StateMachine
    from py_exodus.world import tile_effects

    random.seed(seed)
    tile_effects._rng.seed(seed)
    batch._seed_dungeon_rngs()
    party = batch.build_party()
    sm = StateMachine(asset_mgr=am, audio=None)
    sm.set_screen(OverworldScreen(party=party, asset_mgr=am))
    ctrl = AutoPlayController(enabled=True, step_interval=0.08)
    sm.autoplay_enabled = True
    got: dict[str, pygame.Surface] = {}
    frame = 0
    while len(got) < len(wants) and frame < 2_000_000:
        ctrl.update(batch.FRAME_DT, sm)
        sm.update(batch.FRAME_DT)
        frame += 1
        name = type(sm.current_screen).__name__
        if name in wants and name not in got and frame >= wants[name]:
            surf = pygame.Surface(SIZE)
            sm.autoplay_enabled = False  # the panel as a player sees it
            sm.render(surf)
            sm.autoplay_enabled = True
            got[name] = surf
            print(f"{name}: frame {frame}")
        if party.is_party_dead() or getattr(party, "exodus_defeated", 0):
            break
    return got


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--sosaria-frame", type=int, default=459_000)
    ap.add_argument("--dungeon-frame", type=int, default=290_400)
    args = ap.parse_args()

    pygame.init()
    pygame.display.set_mode(SIZE)
    from py_exodus.autoplay import batch

    am = batch._assets()
    OUT.mkdir(parents=True, exist_ok=True)
    shots = {
        "intro": _intro_frame(am, view_only=False, seconds=22),
        "view": _intro_frame(am, view_only=True, seconds=12),
        "menu": _menu(am),
    }
    played = _play(
        am,
        args.seed,
        {"OverworldScreen": args.sosaria_frame, "DungeonScreen": args.dungeon_frame},
    )
    if "OverworldScreen" in played:
        shots["sosaria"] = played["OverworldScreen"]
    if "DungeonScreen" in played:
        shots["dungeon"] = played["DungeonScreen"]
    for name, surf in shots.items():
        pygame.image.save(surf, OUT / f"{name}.png")
        print(f"wrote {OUT / f'{name}.png'}")


if __name__ == "__main__":
    main()
