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


def test_moons_start_at_phase_four():
    """UltimaMain.c:36: ``short gMoon[2] = {12,4}, gMoonDisp[2] =
    {'4','4'}`` -- both moons start at phase 4 with fresh countdowns, so a
    new game has neither the double new moon (Dawn) nor the gate at site 0.
    Trammel turns on the 12th Sosaria turn, Felucca on the 4th
    (UltimaMisc.c:1493-1506). The port started at phase 0 (both new)."""
    from py_exodus.screens.overworld import OverworldScreen

    p = Party()
    assert (p.moon_phase, p.moon_turns) == (12, 0)
    scr = OverworldScreen.__new__(OverworldScreen)
    scr.party = p
    assert (scr.trammel_phase, scr.felucca_phase) == (4, 4)
    for _ in range(4):
        p.advance_moons()
    assert (scr.trammel_phase, scr.felucca_phase) == (4, 5)
    for _ in range(8):
        p.advance_moons()
    assert (scr.trammel_phase, scr.felucca_phase) == (5, 7)


def test_moongate_old_save_keeps_its_phase():
    """A save from before the change carries its own moon_phase and loads it
    unchanged; one with no moon keys loads phase 0, as before."""
    p = _party()
    p.moon_phase, p.moon_turns = 5, 7
    d = p.to_dict()
    q = Party.from_dict(d)
    assert (q.moon_phase, q.moon_turns) == (5, 7)
    del d["moon_phase"], d["moon_turns"]
    assert Party.from_dict(d).moon_phase == 0


def test_routine6e35_moon_step_on_pass(overworld):
    """UltimaMisc.c:1357-1377: every turn (a pass, a refused step, a letter
    command) runs MoonGateUpdate, then ``temp = GetXYVal(xpos, ypos); if
    (temp == 136) HandleMoonStep();`` -- a gate that appears under a party
    standing still sends it on. The port checked only after a step."""
    scr = overworld(x=15, y=29)
    # Phase 12 -> 13 on this turn: Trammel 4 (gate at site 4, (15, 29)),
    # Felucca 5 (destination site 5, (12, 55)).
    scr.party.moon_phase, scr.party.moon_turns = 12, 3
    scr._pass_turn()
    assert (scr.trammel_phase, scr.felucca_phase) == (4, 5)
    assert (scr.party.x, scr.party.y) == (12, 55)


def test_validmonsterdir_gate_and_dawn_closed_to_monsters(overworld):
    """UltimaMisc.c:1555-1566 writes the gate (136) into the map at the
    Trammel site and Dawn's town (24) at LocationX/Y[8] = (37, 53) on a
    double new moon; ValidMonsterDir (UltimaMisc.c:263-272) lets land
    monsters onto 4, 8, 12 and 32 only, so neither is open to them. The
    port's gate is drawn over grass and Dawn over forest, both open."""
    scr = overworld(x=40, y=40)
    scr.party.moon_phase = 12  # Trammel 4: gate at (15, 29)
    assert not scr._lw_monster_terrain_ok("orc", 15, 29)
    assert scr._lw_monster_terrain_ok("orc", 15, 27)  # site 2, no gate now
    assert scr._lw_monster_terrain_ok("orc", 37, 53)  # Dawn is forest
    scr.party.moon_phase = 0  # double new moon: Dawn shows, gate at (8, 8)
    assert not scr._lw_monster_terrain_ok("orc", 37, 53)
    assert not scr._lw_monster_terrain_ok("orc", 8, 8)
    assert scr._lw_monster_terrain_ok("orc", 15, 29)


def test_spawnmonster_never_on_the_gate(overworld, monkeypatch):
    """UltimaMisc.c:1177-1180: a spawn needs the map value to be the type's
    start terrain (4 or 0); the gate's 136 is neither."""
    from py_exodus.screens import overworld as ow

    scr = overworld(x=40, y=40)
    scr.party.moon_phase = 12  # gate at (15, 29), on grass
    monkeypatch.setattr(ow, "random", Script([134, 15, 29]))
    scr._spawn_wandering_creature()
    assert not any((c["x"], c["y"]) == (15, 29) for c in scr.creatures)


# --- SafeExodus, INSERT ---------------------------------------------------------


def _exodus_party() -> tuple[Party, PartyMember]:
    m = _pm("Carder")
    m.player.cards = [1, 1, 1, 1]
    return _party(m), m


def test_safeexodus_on_entry_after_exodus_falls(town):
    """UltimaMain.c:1515-1517: entering Castle Exodus with ``Party[16] ==
    1`` runs SafeExodus (UltimaMisc.c:2512-2527): every monster there is
    removed and x 0x1E..0x21, y 1..11 become floor (0x20), opening the way
    north past the machine. The port kept the castle's people and walls."""
    p, _ = _exodus_party()
    p.exodus_defeated = 1
    p.exodus_cards_status = 0xF
    scr = town(map_id=2, x=32, y=62, party=p)
    scr.on_enter()
    assert scr.game_map.npcs == []
    for x in range(30, 34):
        for y in range(1, 12):
            assert scr.game_map.get_tile(x, y).name == "floor", (x, y)
    assert scr.game_map.get_tile(29, 9).name == "moongate"


def test_safeexodus_not_before_exodus_falls(town):
    """UltimaMain.c:1515: SafeExodus only once ``Party[16] == 1``."""
    p, _ = _exodus_party()
    scr = town(map_id=2, x=32, y=62, party=p)
    scr.on_enter()
    assert scr.game_map.npcs
    assert scr.game_map.get_tile(31, 3).name == "water"


def test_insert_last_card_runs_safeexodus(town):
    """UltimaMisc.c:2357-2359, 2424: the fourth card sets ``Party[16] = 1``
    and, after the ending, ``SafeExodus();`` clears the castle at once."""
    from py_exodus.screens import final

    p, _ = _exodus_party()
    scr = town(map_id=2, x=33, y=12, party=p)
    p.exodus_cards_status = 0x7  # Love, Sol, Moons in (this visit, C-29)
    final.prompt_insert_card(scr, 33, 12)
    _key(scr, pygame.K_1, "1")
    _key(scr, pygame.K_d, "d")
    assert p.exodus_defeated == 1
    assert scr.game_map.npcs == []
    assert scr.game_map.get_tile(31, 3).name == "floor"


def test_insert_card_stays_with_member():
    """UltimaMisc.c:2328-2343: INSERT tests the card bit (``Player[rosNum][14]
    & bytes``) and never clears it, so the member keeps the card. The port
    took it away (Java)."""
    from py_exodus.screens.final import FinalScreen

    p, m = _exodus_party()
    scr = FinalScreen(party=p)
    assert scr.insert_card("love", member_idx=0, pos=(30, 12)) is True
    assert m.player.cards == [1, 1, 1, 1]
    assert p.exodus_cards_status == 0x1


# --- Saves ------------------------------------------------------------------------




# --- Saves ------------------------------------------------------------------------


def test_putsosaria_keeps_every_parked_object(tmp_path):
    """UltimaMisc.c:838-843: PutSosaria writes the whole map grid, so every
    parked ship, horse and dropped chest (each a map value) is saved. The
    port (Java Context.saveGame) kept the oldest 24."""
    from py_exodus.save_system import SaveSystem

    p = _party()
    objs = [{"tile": "chest", "x": 10 + i, "y": 40} for i in range(30)]
    p.dynamic_objects.extend(objs)
    p.sosaria_objects.extend(objs[:26])
    d = p.to_dict()
    assert d["dynamic_objects"] == objs
    assert d["sosaria_objects"] == objs[:26]
    path = tmp_path / "party.json"
    SaveSystem.save_game(p, path)
    assert SaveSystem.load_game(path).dynamic_objects == objs


# --- W-18 (user ruling 2026-11-25, revised): the wind still rules after Exodus


def test_after_exodus_the_wind_still_stops_a_ship(overworld):
    """LW's ValidTrans (UltimaMain.c:3222-3225) returns TRUE once Party[16]
    is set; the user ruled against it (no Apple II source for it): a calm
    and a headwind still stop a ship after Exodus falls."""
    from py_exodus.constants import Direction

    ow = overworld(50, 13)
    ow.party.transport = Transport.SHIP
    ow.party.exodus_defeated = 1
    ow.party.wind_direction = None
    _key(ow, pygame.K_UP)
    assert (ow.party.x, ow.party.y) == (50, 13)
    assert "The ship is becalmed!" in ow.text_log.history
    ow.party.wind_direction = Direction.NORTH
    _key(ow, pygame.K_UP)
    assert (ow.party.x, ow.party.y) == (50, 13)
    assert "Headwinds block thy ship!" in ow.text_log.history
