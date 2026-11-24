"""LairWare parity, batch W (moongates, shrines, Exodus and world state).

Each test pins one rule from the LairWare Mac port (refs/ultima3/Sources),
the rules authority; the docstring quotes the File.c:line it ports. Ledger:
docs/superpowers/plans/lw-parity-ledger.md, table "W - World".
"""
from __future__ import annotations

import pygame
import pytest

from py_exodus.constants import Profession, Race, Status, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember


class Script:
    """Stand-in for the ``random`` module: randint(a, b) pops scripted rolls
    (an empty script answers ``a``)."""

    def __init__(self, rolls: list[int]) -> None:
        self.rolls = list(rolls)

    def randint(self, a: int, b: int) -> int:
        v = self.rolls.pop(0) if self.rolls else a
        assert a <= v <= b, (v, a, b)
        return v

    def randrange(self, n: int) -> int:
        v = self.rolls.pop(0) if self.rolls else 0
        assert 0 <= v < n, (v, n)
        return v

    def random(self) -> float:
        return 0.5

    def choice(self, seq):
        return seq[0]

    def shuffle(self, seq) -> None:
        return None


def _pm(name: str = "Hero", **kw) -> PartyMember:
    d = {"hp": 300, "max_hp": 300, "gold": 100}
    d.update(kw)
    return PartyMember(Character(name, "M", Race.HUMAN, Profession.FIGHTER, **d))


def _party(*members: PartyMember) -> Party:
    party = Party(list(members) or [_pm()], transport=Transport.FOOT)
    for m in party.members:
        m.submorsels = 400
    return party


def _key(screen, k: int, uni: str = "") -> None:
    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k, unicode=uni))


@pytest.fixture
def overworld(pygame_setup, asset_mgr):
    from py_exodus.screens.overworld import OverworldScreen

    def make(x: int = 40, y: int = 40, party: Party | None = None, map_id: int = 0):
        scr = OverworldScreen(
            party=party or _party(), map_id=map_id, asset_mgr=asset_mgr,
            start_x=x, start_y=y, random_encounters=False,
        )
        scr.party.x, scr.party.y = x, y
        scr.party.objects_map_id = map_id
        scr.creatures = []
        return scr

    return make


@pytest.fixture
def town(pygame_setup, asset_mgr):
    from py_exodus.screens.town import TownScreen

    def make(map_id: int = 3, x: int = 32, y: int = 32, party: Party | None = None):
        scr = TownScreen(party=party or _party(), map_id=map_id, asset_mgr=asset_mgr,
                         start_x=x, start_y=y)
        scr.avatar_x, scr.avatar_y = x, y
        return scr

    return make


# --- Moongates --------------------------------------------------------------


def test_handlemoonstep_castle_gate_sends_to_random_grass(town, monkeypatch):
    """UltimaMain.c:3209-3210: ``if ((value == 136) || (value == 248)) value
    = 4;`` -- the gate tile (0x22) is walkable everywhere. Routine6E35
    (UltimaMisc.c:1375-1377) then runs HandleMoonStep, which off Sosaria
    (UltimaMisc.c:1579-1585) rolls ``xpos = RandNum(0, gCurMapSize - 1);
    ypos = RandNum(0, gCurMapSize - 1);`` until the map value is 4 (grass).
    Castle British has gates at (19-22, 43); the port's tile was solid."""
    from py_exodus.screens import town as town_mod

    scr = town(map_id=1, x=19, y=44)
    gm = scr.game_map
    assert gm.get_tile(19, 43).name == "moongate"
    assert gm.get_tile(30, 30).name != "grass"  # first roll: refused
    assert gm.get_tile(0, 5).name == "grass"
    monkeypatch.setattr(town_mod, "random", Script([30, 30, 0, 5]))
    scr._try_move(__import__("py_exodus.constants", fromlist=["Direction"]).Direction.NORTH)
    assert (scr.avatar_x, scr.avatar_y) == (0, 5)


def test_moongate_new_moon_site_is_8_8(overworld):
    """MISC 400 (MoonXTable/MoonYTable, read by GetMiscStuff,
    UltimaMisc.c:169-172) holds X 8, 57, 15, 36, 15, 12, 31, 58 and Y 8, 46,
    27, 58, 29, 55, 31, 31: the new-moon gate stands at (8, 8); the port had
    (7, 8). The other seven sites already matched."""
    scr = overworld()
    sites = {g.phase: (g.x, g.y) for g in scr.game_map.moongates}
    assert sites == {
        0: (8, 8), 1: (57, 46), 2: (15, 27), 3: (36, 58),
        4: (15, 29), 5: (12, 55), 6: (31, 31), 7: (58, 31),
    }


# --- SafeExodus, INSERT ---------------------------------------------------------


def _exodus_party() -> tuple[Party, PartyMember]:
    m = _pm("Carder")
    m.player.cards = [1, 1, 1, 1]
    return _party(m), m


# --- Saves ------------------------------------------------------------------------


