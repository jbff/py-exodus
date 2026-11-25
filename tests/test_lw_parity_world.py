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


def _castle_at_last_panel(asset_mgr, p):
    """A state machine on Castle Exodus at the Death panel, Love, Sol and
    Moons already in (this visit, C-29)."""
    from py_exodus.screens.town import TownScreen
    from py_exodus.state_machine import StateMachine

    sm = StateMachine(asset_mgr=asset_mgr)
    scr = TownScreen(party=p, map_id=2, asset_mgr=asset_mgr, start_x=33, start_y=12)
    scr.avatar_x, scr.avatar_y = 33, 12
    sm.set_screen(scr)
    p.exodus_cards_status = 0x7
    return sm, scr


def test_the_game_ends_when_exodus_falls(pygame_setup, asset_mgr):
    """User ruling 2026-11-25: the game ends when Exodus falls, as the 8-bit
    originals did. The fourth card (UltimaMisc.c:2357-2359) still shows the
    ending; its closing key returns to the title screen the way a dead
    party's game over does, and play never goes on in the castle."""
    from py_exodus.screens import final
    from py_exodus.screens.start import StartScreen

    p, _ = _exodus_party()
    sm, scr = _castle_at_last_panel(asset_mgr, p)
    final.prompt_insert_card(scr, 33, 12)
    _key(scr, pygame.K_1, "1")
    _key(scr, pygame.K_d, "d")
    assert isinstance(sm.current_screen, final.FinalScreen)
    assert sm.current_screen.victory and p.exodus_defeated == 1
    _key(sm.current_screen, pygame.K_SPACE)
    sm.update(0.0)
    assert isinstance(sm.current_screen, StartScreen)
    assert sm.screen_stack == [sm.current_screen]  # the castle is gone
    assert sm.current_screen.party is p


@pytest.mark.parametrize("k", [pygame.K_RETURN, pygame.K_ESCAPE])
def test_every_closing_key_of_the_ending_goes_to_the_title(pygame_setup, asset_mgr, k):
    """Enter and Escape close the ending as Space does: to the title."""
    from py_exodus.screens import final
    from py_exodus.screens.start import StartScreen

    p, _ = _exodus_party()
    sm, scr = _castle_at_last_panel(asset_mgr, p)
    final.prompt_insert_card(scr, 33, 12)
    _key(scr, pygame.K_1, "1")
    _key(scr, pygame.K_d, "d")
    _key(sm.current_screen, k)
    sm.update(0.0)
    assert isinstance(sm.current_screen, StartScreen)


def _castle_screen_factory(asset_mgr):
    from py_exodus.screens.town import TownScreen

    def make(party, **_kw):
        scr = TownScreen(party=party, map_id=2, asset_mgr=asset_mgr, start_x=30, start_y=12)
        scr.avatar_x, scr.avatar_y = 30, 12
        scr.game_map.npcs = []  # insertion only, no fights
        return scr

    return make


def _card_party4() -> Party:
    members = [_pm(n) for n in ("Carder", "B", "C", "D")]
    members[0].player.cards = [1, 1, 1, 1]
    return _party(*members)


def test_batch_counts_the_new_ending_as_a_win(pygame_setup, asset_mgr, monkeypatch, tmp_path):
    """User ruling 2026-11-25 (the game ends when Exodus falls): a headless
    batch (autoplay/batch.py run_seed) still stops at the fourth card with
    WON, and writes no save."""
    from py_exodus.autoplay import batch
    from py_exodus.screens import overworld as overworld_mod

    monkeypatch.chdir(tmp_path)
    party = _card_party4()
    monkeypatch.setattr(batch, "build_party", lambda: party)
    monkeypatch.setattr(batch, "_assets", lambda: asset_mgr)
    monkeypatch.setattr(overworld_mod, "OverworldScreen", _castle_screen_factory(asset_mgr))
    res = batch.run_seed(1, tmp_path / "traces", max_steps=400)
    assert res["outcome"].startswith("WON@"), res
    assert party.exodus_defeated == 1
    assert not (tmp_path / "saves").exists()


def test_live_autoplay_stops_cleanly_at_the_ending(pygame_setup, asset_mgr, monkeypatch, tmp_path):
    """Live autoplay inserts the cards, leaves the ending alone, and once
    the closing key brings the title it switches itself off instead of
    pressing Journey Onward (which would resume the pre-castle save)."""
    from py_exodus.autoplay import AutoPlayController
    from py_exodus.screens.final import FinalScreen
    from py_exodus.screens.start import StartScreen
    from py_exodus.state_machine import StateMachine

    monkeypatch.chdir(tmp_path)
    (tmp_path / "saves").mkdir()
    (tmp_path / "saves" / "party.json").write_text("{}")  # a pre-castle save
    party = _card_party4()
    sm = StateMachine(asset_mgr=asset_mgr)
    sm.set_screen(_castle_screen_factory(asset_mgr)(party))
    ctrl = AutoPlayController(enabled=True, step_interval=0.01)
    for _ in range(300):
        if isinstance(sm.current_screen, FinalScreen):
            break
        ctrl.step(sm)
    assert isinstance(sm.current_screen, FinalScreen)
    assert ctrl.step(sm) is None  # the ending is left to the player
    _key(sm.current_screen, pygame.K_SPACE)
    sm.update(0.0)
    assert isinstance(sm.current_screen, StartScreen)
    assert ctrl.step(sm) is None
    assert not ctrl.enabled and not sm.autoplay_enabled
    assert isinstance(sm.current_screen, StartScreen)


def test_no_safeexodus_the_castle_is_never_cleared(town):
    """W-15 removed (user ruling 2026-11-25, the game ends when Exodus
    falls): SafeExodus (UltimaMisc.c:2512-2527) cleared Castle Exodus for
    play after the fall. The last card leaves the castle as it stands, and
    an old save that has the flag set enters the castle as it stands too."""
    from py_exodus.screens import final

    assert not hasattr(final, "safe_exodus")
    p, _ = _exodus_party()
    scr = town(map_id=2, x=33, y=12, party=p)
    p.exodus_cards_status = 0x7
    final.prompt_insert_card(scr, 33, 12)
    _key(scr, pygame.K_1, "1")
    _key(scr, pygame.K_d, "d")
    assert p.exodus_defeated == 1
    assert scr.game_map.npcs
    assert scr.game_map.get_tile(31, 3).name == "water"

    old, _ = _exodus_party()
    old.exodus_defeated = 1  # an old save, won under play-on
    scr2 = town(map_id=2, x=32, y=62, party=old)
    scr2.on_enter()
    assert scr2.game_map.npcs
    assert scr2.game_map.get_tile(31, 3).name == "water"


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
