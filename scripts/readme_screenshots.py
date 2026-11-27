"""Render the README screenshots into docs/screenshots/ (headless).

    uv run python scripts/readme_screenshots.py [--seed 1]

- intro.png: the intro during the duel, under the title art.
- view.png: the View, LairWare's demo strip under the title.
- menu.png: the main menu.
- creation.png: a new adventurer at the stats step.
- book_contents.png and book_spread.png: the Book of Lore.
- sosaria.png and dungeon.png: frames from a headless Full Autoplay run of
  the batch party (autoplay/batch.py). At the Sosaria moment, ztats.png,
  peer.png, card_commands.png, card_wizard.png and roster.png are taken
  over the same game. Each is the first frame at or after
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
#: The Book spread shown: the start of "Combat".
BOOK_CHAPTER = 7
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
    """Run autoplay; capture each wanted screen class at or after its frame.
    At the Sosaria moment the UI shots over the map are taken too."""
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
    while not all(n in got for n in wants) and frame < 2_000_000:
        ctrl.update(batch.FRAME_DT, sm)
        sm.update(batch.FRAME_DT)
        frame += 1
        screen = sm.current_screen
        name = type(screen).__name__
        if name in wants and name not in got and frame >= wants[name]:
            sm.autoplay_enabled = False  # the panel as a player sees it
            got[name] = _shot(sm.render)
            if name == "OverworldScreen":
                got.update(_over_the_map(screen, sm, am))
            sm.autoplay_enabled = True
            print(f"{name}: frame {frame}")
        if party.is_party_dead() or getattr(party, "exodus_defeated", 0):
            break
    return got


def _shot(render) -> pygame.Surface:
    surf = pygame.Surface(SIZE)
    render(surf)
    return surf


def _over_the_map(screen, sm, am) -> dict[str, pygame.Surface]:
    """Ztats, Peer, the F3/F4 cards and the roster, with this party."""
    from py_exodus.screens.quickref import QuickRefScreen
    from py_exodus.screens.roster_screen import RosterScreen

    out: dict[str, pygame.Surface] = {}
    wizard = next(
        (i for i, m in enumerate(screen.party.members) if m.profession.name == "WIZARD"), 0
    )
    screen.stats_panel.inspect_index = wizard
    out["ztats"] = _shot(screen.render)
    screen.stats_panel.inspect_index = None

    screen.gem_view_active = True
    out["peer"] = _shot(screen.render)
    screen.gem_view_active = False

    for card in ("commands", "wizard"):
        ref = QuickRefScreen(card=card, return_screen=screen, manager=sm)
        out[f"card_{card}"] = _shot(ref.render)

    roster = list(screen.party.members) + _extra_adventurers()
    rs = RosterScreen(party=screen.party, roster=roster, asset_mgr=am, manager=None)
    rs.selected_roster_idx = 3
    out["roster"] = _shot(rs.render)
    return out


def _extra_adventurers():
    """A few level-1 characters so the roster list isn't only the party."""
    from py_exodus.constants import ArmorType, Profession, Race, Sex, WeaponType
    from py_exodus.entities.character import Character

    specs = (
        ("BRANWEN", Sex.FEMALE, Race.HUMAN, Profession.PALADIN, 20, 15, 5, 10),
        ("OSRIC", Sex.MALE, Race.DWARF, Profession.BARBARIAN, 25, 20, 5, 5),
        ("LIRA", Sex.FEMALE, Race.ELF, Profession.RANGER, 10, 20, 10, 10),
    )
    return [
        Character(n, sx, r, p, strength=a, dexterity=b, intelligence=c, wisdom=d,
                  gold=150, weapon=WeaponType.DAGGER, armor=ArmorType.CLOTH)
        for n, sx, r, p, a, b, c, d in specs
    ]


def _creation(am) -> pygame.Surface:
    """A new adventurer at the stats step: a Druid being shaped."""
    from py_exodus.screens.roster_screen import RosterScreen

    rs = RosterScreen(roster=_extra_adventurers(), asset_mgr=am, manager=None)
    rs._start_create_character()
    rs._step_name("MORWEN")
    rs._step_sex("F")
    rs._step_race("E")
    rs._step_profession("D")
    rs._new_char_data["stats"] = [10, 15, 10, 15]
    rs._stat_sel = 3
    return _shot(rs.render)


def _book(am, chapter: int | None) -> pygame.Surface:
    from py_exodus.screens.book import BookScreen

    book = BookScreen(asset_mgr=am)
    book.render(pygame.Surface(SIZE))  # lays the book out for this size
    if chapter is not None:
        book.open_chapter(chapter)
    return _shot(book.render)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--sosaria-frame", type=int, default=459_000)
    ap.add_argument("--dungeon-frame", type=int, default=290_400)
    ap.add_argument("--only", help="comma-separated shot names to write (default: all)")
    args = ap.parse_args()

    pygame.init()
    pygame.display.set_mode(SIZE)
    from py_exodus.autoplay import batch

    am = batch._assets()
    OUT.mkdir(parents=True, exist_ok=True)
    shots = {
        "intro": lambda: _intro_frame(am, view_only=False, seconds=22),
        "view": lambda: _intro_frame(am, view_only=True, seconds=12),
        "menu": lambda: _menu(am),
        "creation": lambda: _creation(am),
        "book_contents": lambda: _book(am, None),
        "book_spread": lambda: _book(am, BOOK_CHAPTER),
    }
    only = set(args.only.split(",")) if args.only else None
    images = {n: make() for n, make in shots.items() if only is None or n in only}
    played_names = {"sosaria", "dungeon", "ztats", "peer", "card_commands", "card_wizard", "roster"}
    if only is None or only & played_names:
        played = _play(
            am,
            args.seed,
            {"OverworldScreen": args.sosaria_frame, "DungeonScreen": args.dungeon_frame},
        )
        played["sosaria"] = played.pop("OverworldScreen", None)
        played["dungeon"] = played.pop("DungeonScreen", None)
        images.update(
            (n, img) for n, img in played.items()
            if img is not None and (only is None or n in only)
        )
    for name, surf in images.items():
        pygame.image.save(surf, OUT / f"{name}.png")
        print(f"wrote {OUT / f'{name}.png'}")

if __name__ == "__main__":
    main()
