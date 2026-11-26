"""LairWare parity, batch W (moongates, shrines, Exodus and world state).

Each test pins one rule from the LairWare Mac port (refs/ultima3/Sources),
the rules authority; the docstring quotes the File.c:line it ports. Ledger:
docs/superpowers/plans/lw-parity-ledger.md, table "W - World".
"""
from __future__ import annotations

import pygame
import pytest
from conftest import play_out_ending

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
    play_out_ending(sm)
    assert isinstance(sm.current_screen, StartScreen)
    assert sm.screen_stack == [sm.current_screen]  # the castle is gone
    assert sm.current_screen.party is p


@pytest.mark.parametrize("k", [pygame.K_RETURN, pygame.K_ESCAPE])
def test_every_closing_key_of_the_ending_goes_to_the_title(pygame_setup, asset_mgr, k):
    """Enter and Escape work the ending's key waits as Space does: to the title."""
    from py_exodus.screens import final
    from py_exodus.screens.start import StartScreen

    p, _ = _exodus_party()
    sm, scr = _castle_at_last_panel(asset_mgr, p)
    final.prompt_insert_card(scr, 33, 12)
    _key(scr, pygame.K_1, "1")
    _key(scr, pygame.K_d, "d")
    play_out_ending(sm, k)
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
    play_out_ending(sm)
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


# --- W-12 / R-18 / W-20: classic AutoSave (user ruling 2026-11-25) ------------------


@pytest.fixture
def autosaving(pygame_setup, asset_mgr, monkeypatch, tmp_path):
    """A live-game state machine (autosave on, as GameApp sets it with a
    window) on Sosaria, saving into a temporary directory."""
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.state_machine import StateMachine

    monkeypatch.chdir(tmp_path)

    def make(x: int = 40, y: int = 40, party: Party | None = None):
        sm = StateMachine(asset_mgr=asset_mgr)
        sm.autosave_enabled = True
        party = party or _party(_pm("A"), _pm("B"))
        ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr,
                             start_x=x, start_y=y, random_encounters=False)
        party.x, party.y = x, y
        sm.set_screen(ow)
        ow.creatures = [ow._lw_start_whirlpool()]
        return sm, ow

    return make


def _saved(tmp_path=None) -> dict | None:
    from pathlib import Path

    from py_exodus.save_system import SaveSystem

    path = Path("saves/party.json")
    return SaveSystem.load_game_data(path) if path.exists() else None


@pytest.mark.parametrize("pos, dest", [((46, 19), 3), ((56, 6), 14), ((10, 53), 2)])
def test_autosave_on_entering_a_town_dungeon_or_castle(autosaving, pos, dest):
    """UltimaMain.c:1486-1494 (enterdone)::

        if (CFPreferencesGetAppBooleanValue(U3PrefAutoSave, ...)) {
            PutRoster(); PutParty(); PutSosaria();

    LW's classic preferences set AutoSave (PrefsDialog.m:111): entering a
    town, castle (Castle Exodus too) or dungeon saves the game on Sosaria,
    at the entrance, before the new map loads."""
    sm, ow = autosaving(*pos)
    assert _saved() is None
    ow._enter_portal()
    assert type(sm.current_screen).__name__ != "OverworldScreen"
    data = _saved()
    assert data is not None
    assert (data["x"], data["y"]) == pos
    assert [m["tile_name"] for m in data["overworld"]["monsters"]] == ["whirlpool"]


def test_autosave_on_leaving_a_town(autosaving):
    """UltimaMisc.c:1336-1347 (Routine6E6B): back on Sosaria, AutoSave
    writes roster, party and Sosaria."""
    from pathlib import Path

    sm, ow = autosaving(46, 19)
    ow._enter_portal()
    Path("saves/party.json").unlink()
    town = sm.current_screen
    town.party.members[0].gold = 777
    town._exit_town()
    sm.update(0.0)
    assert sm.current_screen is ow
    data = _saved()
    assert (data["x"], data["y"]) == (46, 19)
    assert data["members"][0]["gold"] == 777


def test_autosave_on_leaving_a_dungeon(autosaving):
    """UltimaMisc.c:1336-1347: Routine6E6B runs for dungeons as for towns."""
    from pathlib import Path

    sm, ow = autosaving(56, 6)
    ow._enter_portal()
    Path("saves/party.json").unlink()
    sm.current_screen.exit_screen()
    sm.update(0.0)
    assert sm.current_screen is ow
    assert (_saved()["x"], _saved()["y"]) == (56, 6)


def test_autosave_on_the_whirlpool_trip_in_and_back(autosaving):
    """UltimaMain.c:3048-3060: engulfed, the party is put back on its
    frigate at the engulf spot, the whirlpool moved to (2, 62), PushSosaria,
    then AutoSave writes roster, party and Sosaria before Ambrosia loads.
    UltimaMain.c:3094-3104: back on Sosaria, AutoSave writes roster and
    party."""
    from pathlib import Path

    from py_exodus.world import portal_entry

    sm, ow = autosaving(47, 17)
    ow.party.transport = Transport.SHIP
    ow._check_whirlpool_engulf()
    assert ow.map_id == 13
    data = _saved()
    assert (data["x"], data["y"]) == (47, 17)
    assert data["transport"] == Transport.SHIP.value
    wp = [m for m in data["overworld"]["monsters"] if m["tile_name"] == "whirlpool"]
    assert [(m["x"], m["y"]) for m in wp] == [(2, 62)]

    Path("saves/party.json").unlink()
    ow.party.transport = Transport.SHIP
    assert portal_entry.step_in_whirlpool_portal(ow, 32, 58)
    data = _saved()
    assert (data["x"], data["y"]) == (47, 17)
    assert ow.map_id == 0


def test_autosave_when_a_member_dies(autosaving):
    """UltimaMain.c:3254-3266 (HPSubtract)::

        Player[rosNum][17] = 'D';
        if (CFPreferencesGetAppBooleanValue(U3PrefAutoSave, ...)) {
            Party[4] = xpos; Party[5] = ypos;
            PutParty(); PutRoster();

    Each death saves, anywhere (a town here); the party's place is its
    Sosaria square."""
    sm, ow = autosaving(46, 19)
    ow._enter_portal()
    from pathlib import Path
    Path("saves/party.json").unlink()
    town = sm.current_screen
    town.party.members[1].apply_damage(999)
    data = _saved()
    assert data["members"][1]["status"] in ("D", "DEAD", Status.DEAD.value, Status.DEAD.name)
    assert data["members"][0]["hp"] == 300
    assert (data["x"], data["y"]) == (46, 19)


def test_autosave_when_a_member_dies_in_combat(autosaving):
    """HPSubtract saves in combat too (UltimaMain.c:3254-3266)."""
    sm, ow = autosaving()
    ow._trigger_combat("orc")
    assert type(sm.current_screen).__name__ == "CombatScreen"
    assert _saved() is None  # starting a fight saves nothing
    ow.party.members[0].apply_damage(999, True)
    data = _saved()
    assert data is not None
    assert data["members"][0]["hp"] == 0


def test_autosave_on_a_party_wipe_before_game_over(autosaving):
    """UltimaMain.c:2798-2810 (CheckAllDead): "ALL PLAYERS OUT!", then
    AutoSave writes party, roster and Sosaria before the resurrect-or-quit
    alert. The port saves the dead party before its game over; Journey
    Onward then finds no living party and opens the empty roster (item 43),
    no crash and no loop."""
    from py_exodus.screens.roster_screen import RosterScreen
    from py_exodus.screens.start import StartScreen

    sm, ow = autosaving()
    for m in ow.party.members:
        m.hp, m.status = 0, Status.DEAD
    assert ow.check_party_death()
    assert isinstance(sm.current_screen, StartScreen) and sm.current_screen.game_over
    data = _saved()
    assert all(m["hp"] == 0 for m in data["members"])
    sm.current_screen._start_journey()
    assert isinstance(sm.current_screen, RosterScreen)
    assert sm.current_screen.party.members == []


def test_no_autosave_after_victory(autosaving):
    """User ruling 2026-11-25: no save after the ending; the last save is
    the one made on entering Castle Exodus."""
    from pathlib import Path

    from py_exodus.screens import final
    from py_exodus.screens.start import StartScreen

    p, _ = _exodus_party()
    sm, ow = autosaving(10, 53, party=p)
    ow._enter_portal()
    before = Path("saves/party.json").read_text()
    castle = sm.current_screen
    castle.game_map.npcs = []
    castle.avatar_x, castle.avatar_y = 33, 12
    p.exodus_cards_status = 0x7
    final.prompt_insert_card(castle, 33, 12)
    _key(castle, pygame.K_1, "1")
    _key(castle, pygame.K_d, "d")
    play_out_ending(sm)
    assert isinstance(sm.current_screen, StartScreen)
    assert Path("saves/party.json").read_text() == before
    assert _saved()["exodus_defeated"] == 0


def test_autosave_never_in_headless_batches_tests_or_autoplay(
    pygame_setup, asset_mgr, monkeypatch, tmp_path
):
    """Autosaves are for the player's own game: a headless GameApp (and so a
    batch), a test's StateMachine and live autoplay never write the save,
    whatever happens (an entry, a death, an exit, a wipe)."""
    from py_exodus.__main__ import GameApp
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.state_machine import StateMachine

    monkeypatch.chdir(tmp_path)
    app = GameApp(assets_dir=str(asset_mgr.assets_dir), headless=True, sound_enabled=False)
    assert app.state_machine.autosave_enabled is False
    app.cleanup()
    pygame.init()

    def play(sm) -> None:
        party = _party(_pm("A"), _pm("B"))
        ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr,
                             start_x=46, start_y=19, random_encounters=False)
        party.x, party.y = 46, 19
        sm.set_screen(ow)
        ow._enter_portal()
        party.members[1].apply_damage(999)
        sm.current_screen._exit_town()
        sm.update(0.0)
        for m in party.members:
            m.hp, m.status = 0, Status.DEAD
        sm.current_screen.check_party_death()

    plain = StateMachine(asset_mgr=asset_mgr)
    assert plain.autosave_enabled is False
    play(plain)
    live_autoplay = StateMachine(asset_mgr=asset_mgr)
    live_autoplay.autosave_enabled = True
    live_autoplay.autoplay_enabled = True
    play(live_autoplay)
    assert not (tmp_path / "saves").exists()


# --- Fix round (review of 4a6063f..d10ae75) ----------------------------------------


def _slotted_party() -> Party:
    """Two members holding roster slots 1 and 2, with the roster saved."""
    from pathlib import Path

    from py_exodus.save_system import SaveSystem

    a, b = _pm("A"), _pm("B")
    a.player.roster_slot, b.player.roster_slot = 1, 2
    a.player.cards = [1, 1, 1, 1]
    p = _party(a, b)
    Path("saves").mkdir(exist_ok=True)
    SaveSystem.save_roster([Character.from_dict(m.player.to_dict()) for m in p.members],
                           "saves/roster.json")
    return p


def _roster_on_disk() -> dict[int, Character]:
    from py_exodus.save_system import SaveSystem

    return {c.roster_slot: c for c in SaveSystem.load_roster("saves/roster.json")}


def test_after_victory_the_title_forgets_the_won_party(autosaving):
    """The won party in memory must not reach the roster screen as the
    party in use: New Game / Roster reads the save from disk (the one made
    on entering Castle Exodus), and that save survives."""
    from pathlib import Path

    from py_exodus.screens import final
    from py_exodus.screens.roster_screen import RosterScreen
    from py_exodus.screens.start import StartScreen

    p = _slotted_party()
    sm, ow = autosaving(10, 53, party=p)
    ow._enter_portal()
    castle = sm.current_screen
    castle.game_map.npcs = []
    p.members[0].gold = 4321  # changed after the pre-castle save
    p.exodus_cards_status = 0x7
    final.prompt_insert_card(castle, 33, 12)
    _key(castle, pygame.K_1, "1")
    _key(castle, pygame.K_d, "d")
    play_out_ending(sm)
    title = sm.current_screen
    assert isinstance(title, StartScreen) and not title.game_over
    assert title.party is p and p.exodus_defeated == 1  # autoplay and the trace
    title._new_game()
    roster = sm.current_screen
    assert isinstance(roster, RosterScreen)
    assert roster.party is not p
    assert roster.party.members[0].gold == 100  # the pre-castle save
    assert Path("saves/party.json").exists()
    roster._disperse_party()
    assert _roster_on_disk()[1].gold == 100


def test_a_wipe_leaves_the_roster_dead(autosaving):
    """UltimaMain.c:2798-2810 (CheckAllDead) and 3254-3266 (HPSubtract) run
    PutRoster too: after a wipe the roster records of the party lie dead,
    and Journey Onward (no living party) opens the roster showing them."""
    from py_exodus.screens.roster_screen import RosterScreen

    p = _slotted_party()
    sm, ow = autosaving(party=p)
    p.members[0].apply_damage(999)
    assert _roster_on_disk()[1].is_dead() and not _roster_on_disk()[2].is_dead()
    p.members[1].apply_damage(999, True)
    assert ow.check_party_death()
    disk = _roster_on_disk()
    assert disk[1].is_dead() and disk[2].is_dead()
    sm.current_screen._start_journey()
    scr = sm.current_screen
    assert isinstance(scr, RosterScreen) and scr.party.members == []
    assert {c.roster_slot: c.is_dead() for c in scr.roster} == {1: True, 2: True}


def test_entry_and_exit_autosaves_keep_the_roster_in_step(autosaving):
    """UltimaMain.c:1486-1494 and UltimaMisc.c:1336-1347: PutRoster with
    PutParty, so each roster record matches its member after a save."""
    p = _slotted_party()
    sm, ow = autosaving(46, 19, party=p)
    p.members[0].gold = 555
    ow._enter_portal()
    assert _roster_on_disk()[1].gold == 555
    sm.current_screen.party.members[1].gold = 666
    sm.current_screen._exit_town()
    sm.update(0.0)
    disk = _roster_on_disk()
    assert (disk[1].gold, disk[2].gold) == (555, 666)


def test_leaving_a_dungeon_resets_its_level(autosaving, monkeypatch):
    """UltimaMisc.c:1336 (Routine6E6B) ``Party[3] = 0; // back to surface``:
    by the ladder or Sequitu, the party is on the surface again before the
    exit save, so a surface chest's bomb uses level 0 (8 + roll)."""
    from py_exodus.world import chests
    from py_exodus.world.dungeon import DungeonEvent, DungeonEventType

    for how in ("ladder", "sequitu"):
        sm, ow = autosaving(56, 6)
        ow._enter_portal()
        dscr = sm.current_screen
        dscr.party.dungeon_level = 5
        if how == "ladder":
            dscr._process_event(DungeonEvent(type=DungeonEventType.EXIT_DUNGEON, message=""))
        else:
            dscr._process_event(dscr.state.spell_exit())
        sm.update(0.0)
        assert sm.current_screen is ow
        assert ow.party.dungeon_level == 0
        assert _saved()["dungeon_level"] == 0

    rolls = iter([0, 255, 2, 2])
    monkeypatch.setattr(chests.random, "randrange", lambda n: next(rolls, 0))
    hp = ow.party.members[0].hp
    lines, bomb = chests._chest_trap(ow.party, ow.party.members[0])
    assert bomb and ow.party.members[0].hp == hp - 8


def test_a_death_save_inside_a_dungeon_reloads_on_the_surface(autosaving):
    """HPSubtract saves in a dungeon too (UltimaMain.c:3254-3266). The port's
    save is a Sosaria record: the dungeon's entrance square, level 0, and
    Journey Onward resumes there."""
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.screens.start import StartScreen

    sm, ow = autosaving(56, 6)
    ow._enter_portal()
    sm.current_screen.party.dungeon_level = 4
    ow.party.members[1].apply_damage(999)
    data = _saved()
    assert (data["x"], data["y"], data["dungeon_level"]) == (56, 6, 0)
    start = StartScreen(asset_mgr=ow.asset_mgr)
    start._start_journey()
    loaded = start.next_screen
    assert isinstance(loaded, OverworldScreen)
    assert (loaded.party.x, loaded.party.y, loaded.party.dungeon_level) == (56, 6, 0)
    assert loaded.party.members[1].is_dead() and not loaded.party.members[0].is_dead()


def test_a_death_save_in_combat_reloads(autosaving):
    """The combat death save keeps the party's Sosaria square, and Journey
    Onward resumes it there with the member dead."""
    from py_exodus.screens.start import StartScreen

    sm, ow = autosaving(30, 40)
    ow._trigger_combat("orc")
    ow.party.members[0].apply_damage(999, True)
    data = _saved()
    assert (data["x"], data["y"]) == (30, 40)
    start = StartScreen(asset_mgr=ow.asset_mgr)
    start._start_journey()
    loaded = start.next_screen.party
    assert (loaded.x, loaded.y) == (30, 40)
    assert loaded.members[0].is_dead() and not loaded.members[1].is_dead()


def test_a_death_save_on_ambrosia_mid_combat(autosaving):
    """On Ambrosia the save is the Sosaria record GoWhirlPool left: the
    engulf square, on the frigate, with Sosaria's monsters (the whirlpool at
    (2, 62)), never Ambrosia's position or monsters."""
    from py_exodus.screens.start import StartScreen

    sm, ow = autosaving(47, 17)
    ow.party.transport = Transport.SHIP
    ow._check_whirlpool_engulf()
    assert ow.map_id == 13
    ow.party.x, ow.party.y = 30, 30
    ow._trigger_combat("orc")
    assert type(sm.current_screen).__name__ == "CombatScreen"
    ow.party.members[0].apply_damage(999, True)
    data = _saved()
    assert (data["x"], data["y"]) == (47, 17)
    assert data["transport"] == Transport.SHIP.value
    assert [(m["x"], m["y"]) for m in data["overworld"]["monsters"]] == [(2, 62)]
    start = StartScreen(asset_mgr=ow.asset_mgr)
    start._start_journey()
    loaded = start.next_screen
    assert str(loaded.map_id) == "0"
    assert (loaded.party.x, loaded.party.y) == (47, 17)
    assert loaded.party.members[0].is_dead()


def test_an_old_won_save_loads_as_not_won(pygame_setup, asset_mgr, monkeypatch, tmp_path):
    """Saves from LW's play-on era can carry exodus_defeated = 1. The game
    ends when Exodus falls now (user ruling 2026-11-25), so such a save
    loads as not won and autoplay keeps playing it."""
    from py_exodus.autoplay import AutoPlayController
    from py_exodus.save_system import SaveSystem
    from py_exodus.screens.start import StartScreen
    from py_exodus.state_machine import StateMachine

    monkeypatch.chdir(tmp_path)
    old = _party(_pm("A"), _pm("B"))
    old.exodus_defeated = 1
    SaveSystem.save_game(old, "saves/party.json")
    assert '"exodus_defeated": 1' in (tmp_path / "saves" / "party.json").read_text()
    assert SaveSystem.load_game("saves/party.json").exodus_defeated == 0

    sm = StateMachine(asset_mgr=asset_mgr)
    start = StartScreen(asset_mgr=asset_mgr)
    sm.set_screen(start)
    start._start_journey()
    assert sm.current_screen.party.exodus_defeated == 0
    ctrl = AutoPlayController(enabled=True, step_interval=0.01)
    for _ in range(5):
        ctrl.step(sm)
    assert ctrl.enabled
