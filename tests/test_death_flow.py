"""Task 2: party death flow tests (Java truth: exodus/Party.java:556-577, 572-574,
exodus/GameScreen.java:433-446, exodus/CombatScreen.java:562-589).

A fully-dead party must end the game: screens route to the StartScreen with
game-over messaging, combat defeat ends combat as a loss with no auto-revive,
and damage that leaves at least one member alive must NOT transition.
"""
from __future__ import annotations

import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.constants import Direction, Profession, Race, Status, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.screens.combat_screen import CombatScreen
from py_exodus.screens.dungeon_screen import DungeonScreen
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.state_machine import StateMachine
from py_exodus.save_system import SaveSystem
from py_exodus.world.map import DungeonMap, DungeonTile


@pytest.fixture
def asset_mgr():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


@pytest.fixture
def sm(asset_mgr):
    """State machine rooted on its default StartScreen."""
    return StateMachine(asset_mgr)


def single_member_party(hp: int = 100) -> Party:
    party = Party(members=[], x=44, y=20, gold=100, food=400, transport=Transport.FOOT)
    party.add_member(
        Character(
            name="Hero",
            sex="M",
            race=Race.HUMAN,
            profession=Profession.FIGHTER,
            hp=hp,
            max_hp=100,
        )
    )
    return party


class _AlwaysHitRng:
    """Stub RNG mirroring Java ``rand.nextInt(n) == 0`` succeeding always."""

    def randrange(self, n: int) -> int:
        return 0


# --- PartyMember.apply_damage: the Java-parity damage chokepoint ---


def test_apply_damage_kills_member():
    """A blow past 0 hp sets hp 0 / Status.DEAD (Party.java:563-570)."""
    member = PartyMember(
        Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, hp=5, max_hp=100)
    )
    assert member.apply_damage(6) is True
    assert member.hp == 0
    assert member.status == Status.DEAD


def test_apply_damage_exact_zero_hp_stays_alive():
    """Java: newHp == 0 is not death — only newHp < 0 sets DEAD."""
    member = PartyMember(
        Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, hp=5, max_hp=100)
    )
    member.apply_damage(5)
    assert member.hp == 0
    assert member.status != Status.DEAD


def test_apply_damage_raises_on_party_wipe():
    """Non-combat damage killing the last living member raises (Party.java:572-574)."""
    party = single_member_party(hp=5)
    with pytest.raises(Exception) as excinfo:
        party.active_member.apply_damage(10)
    assert type(excinfo.value).__name__ == "PartyDeathException"


def test_apply_damage_combat_related_wipe_does_not_raise():
    """Combat-related damage never raises; combat loss routes at combat end."""
    party = single_member_party(hp=5)
    member = party.active_member
    member.apply_damage(10, combat_related_damage=True)
    assert member.status == Status.DEAD
    assert party.is_party_dead()


def test_apply_damage_leaving_one_alive_no_exception():
    """Damage that leaves at least one member alive must not raise or route."""
    party = Party(members=[], gold=0, food=100)
    party.add_member(Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, hp=100, max_hp=100))
    party.add_member(Character("Mage", "F", Race.ELF, Profession.WIZARD, hp=6, max_hp=100))
    mage = party.get_member(1)
    mage.apply_damage(3)
    assert mage.hp == 3
    assert mage.status != Status.DEAD
    assert not party.is_party_dead()


def test_apply_damage_is_noop_on_dead_member():
    """Java applyDamage returns False for a dead member (Party.java:559-561)."""
    party = single_member_party(hp=10)
    hero = party.active_member
    hero.apply_damage(11, combat_related_damage=True)
    assert hero.status == Status.DEAD
    assert hero.apply_damage(5) is False
    assert hero.hp == 0


# --- Combat poison tick (removed, Task 12) --------------------------------
#
# Java's CombatScreen.round has no per-round poison tick (the ROUND-ENDED
# poison damage belongs to Party.endTurn, out of the arena). Task 12 deleted
# arena._apply_poison_tick; the combat-loss → game-over routing it fed is
# still locked by tests/test_game_loop.py's defeat tests and the ranged-poison
# mechanics live in tests/test_combat_parity.py.


# --- Journey Onward after game over reads the on-disk save, not the dead party ---


def test_game_over_journey_onward_loads_party_from_save(pygame_setup, asset_mgr, monkeypatch, tmp_path):
    """Java StartScreen.java:100-117: Journey Onward reads party.sav from disk.
    After a game over the in-memory (dead) party must be ignored in favor of
    the save file's party state."""
    monkeypatch.chdir(tmp_path)

    saved_party = single_member_party(hp=77)
    SaveSystem.save_game(saved_party, tmp_path / "saves" / "party.json")

    from py_exodus.screens.start import StartScreen

    dead_party = single_member_party(hp=10)
    dead_party.get_member(0).apply_damage(20, combat_related_damage=True)
    assert dead_party.is_party_dead()

    start = StartScreen(party=dead_party, asset_mgr=asset_mgr, game_over=True)
    start._start_journey()

    from py_exodus.screens.overworld import OverworldScreen

    assert isinstance(start.next_screen, OverworldScreen)
    loaded = start.next_screen.party
    assert not loaded.is_party_dead()
    assert loaded.get_member(0).hp == 77
    assert loaded.get_member(0).status != Status.DEAD


def test_game_over_journey_onward_without_save_falls_back_to_roster(pygame_setup, monkeypatch, tmp_path):
    """Java StartScreen.java:109-111: no valid party record → ManagePartyScreen."""
    monkeypatch.chdir(tmp_path)

    from py_exodus.screens.roster_screen import RosterScreen
    from py_exodus.screens.start import StartScreen

    dead_party = single_member_party(hp=10)
    dead_party.get_member(0).apply_damage(20, combat_related_damage=True)

    start = StartScreen(party=dead_party, game_over=True)
    start._start_journey()

    assert isinstance(start.next_screen, RosterScreen)


def test_journey_onward_without_game_over_reads_disk_save(pygame_setup, monkeypatch, tmp_path):
    """Java StartScreen.java:100-117: Journey Onward reads the party save from
    disk in every case (never the screen-attached party state)."""
    monkeypatch.chdir(tmp_path)

    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.screens.start import StartScreen

    attached = single_member_party(hp=64)
    on_disk = single_member_party(hp=91)
    on_disk.get_member(0).name = "Diskhero"
    SaveSystem.save_game(on_disk, tmp_path / "saves" / "party.json")

    start = StartScreen(party=attached, game_over=False)
    start._start_journey()

    assert isinstance(start.next_screen, OverworldScreen)
    assert start.next_screen.party.get_member(0).name == "Diskhero"
    assert start.next_screen.party.get_member(0).hp == 91


# --- Screen-level game-over routing ---


def test_overworld_starvation_wipe_transitions_to_start_screen(sm, asset_mgr):
    """Starving with one living member wipes the party → StartScreen game over."""
    party = single_member_party(hp=0)
    party.food = 0
    party.moves = 40
    ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr, manager=sm)
    sm.set_screen(ow)

    # Drive the member's submorsels to the crossing point (Party.java:592-639).
    party.get_member(0).submorsels = 5
    ow._pass_turn()

    assert party.is_party_dead()
    assert sm.current_screen is not ow
    from py_exodus.screens.start import StartScreen

    assert isinstance(sm.current_screen, StartScreen)
    assert sm.current_screen.game_over is True
    # Java partyDeath (GameScreen.java:444-446) does not revive the party
    assert party.is_party_dead()


def test_overworld_starvation_leaving_survivor_no_transition(sm, asset_mgr):
    """Damage that leaves one member alive must NOT end the game."""
    party = Party(members=[], gold=0, food=0)
    party.add_member(Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, hp=100, max_hp=100))
    party.add_member(Character("Mage", "F", Race.ELF, Profession.WIZARD, hp=6, max_hp=100))
    party.moves = 40
    ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr, manager=sm)
    sm.set_screen(ow)

    # Original-rules tick order (user-directed deviation 2026-11-10): a
    # food-0 member gets NO heal — the per-turn starvation blow of 2 lands
    # alone (the old Java meal crossing healed +1 first, net −1; the
    # original tick is 2/turn, no regen at food <= 0).
    for m in party.members:
        m.food = 0
        m.submorsels = 5
    ow._pass_turn()

    assert not party.is_party_dead()
    assert sm.current_screen is ow
    assert party.get_member(1).hp == 4


def test_town_starvation_wipe_transitions_to_start_screen(sm, asset_mgr):
    """The town counterpart of the overworld/dungeon starvation wipes: a
    food-0 member passes turns in town (SPACE — Java GameScreen.java:624-628
    pass key; towns drain the 10-submorsel pool per turn, Party.endTurn
    Party.java:592-639) while the per-turn regen tick applies the 2-HP
    starvation blow (Party.tick_regen — user-directed original-rules
    deviation), and the wipe routes to the StartScreen game over."""
    party = single_member_party(hp=1)
    for m in party.members:
        m.food = 0

    from py_exodus.screens.town import TownScreen

    town = TownScreen(party=party, map_id=1, asset_mgr=asset_mgr, manager=sm)
    sm.set_screen(town)

    for _ in range(10):
        town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
        if party.is_party_dead():
            break

    assert party.is_party_dead()
    from py_exodus.screens.start import StartScreen

    assert isinstance(sm.current_screen, StartScreen)
    assert sm.current_screen.game_over is True
    # Java partyDeath (GameScreen.java:444-446) does not revive the party
    assert party.is_party_dead()


def test_dungeon_starvation_wipe_transitions_to_start_screen(sm, asset_mgr):
    """USER-DIRECTED ORIGINAL-RULES DEVIATION (2026-11-10): the dungeon tick
    regenerates AND starves per consumed turn — Java DungeonScreen.finishTurn
    (DungeonScreen.java:1124-1141) never called Party.endTurn, but the
    original rules starve a food-0 party 2 HP per turn everywhere. Food
    still does not DRAIN in the dungeon (no meal crossing — Java truth,
    kept); members whose food is ALREADY 0 take the starvation blow on the
    dungeon move and a wiped party routes to game over."""

    def member(name: str) -> Character:
        char = Character(name, "M", Race.HUMAN, Profession.FIGHTER, hp=0, max_hp=100)
        char.food = 0
        return char

    party = Party(members=[], x=2, y=2, gold=0, food=0, transport=Transport.FOOT)
    party.add_member(member("Hero"))
    party.add_member(member("Mage"))

    dmap = DungeonMap(id=99, name="TestDungeon", width=8, height=8, levels=8)
    dmap.tiles = [
        [
            [
                DungeonTile.WALL
                if x == 0 or x == 7 or y == 0 or y == 7
                else DungeonTile.FLOOR
                for x in range(8)
            ]
            for y in range(8)
        ]
        for z in range(8)
    ]
    dungeon = DungeonScreen(party=party, dungeon_map=dmap, start_x=2, start_y=2, start_z=0)
    sm.set_screen(dungeon)

    dungeon.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP))

    assert party.is_party_dead()
    from py_exodus.screens.start import StartScreen

    assert isinstance(sm.current_screen, StartScreen)
    assert sm.current_screen.game_over is True
    # Dungeon food drain stays off (Java truth): food was already 0 and no
    # submorsel crossing ran.
    assert all(m.food == 0 for m in party.members)


def test_dungeon_tick_starves_food_zero_but_is_count_based(sm, asset_mgr):
    """USER-DIRECTED ORIGINAL-RULES DEVIATION (2026-11-10): the dungeon
    tick applies the original per-turn starvation (food 0 → 2 damage per
    turn) even though Java's dungeon finishTurn never touched the party
    (DungeonScreen.java:1124-1141). A food-0 member is NOT healed (+1
    requires food > 0) and fighters regen no mana (max_mp 0); food does
    not drain on its own."""

    def member(name: str) -> Character:
        char = Character(name, "M", Race.HUMAN, Profession.FIGHTER, hp=6, max_hp=100)
        char.food = 0
        return char

    party = Party(members=[], x=2, y=2, gold=0, food=0, transport=Transport.FOOT)
    party.add_member(member("Hero"))
    party.add_member(member("Mage"))

    dmap = DungeonMap(id=99, name="TestDungeon", width=8, height=8, levels=8)
    dmap.tiles = [
        [
            [
                DungeonTile.WALL
                if x == 0 or x == 7 or y == 0 or y == 7
                else DungeonTile.FLOOR
                for x in range(8)
            ]
            for y in range(8)
        ]
        for z in range(8)
    ]
    dungeon = DungeonScreen(party=party, dungeon_map=dmap, start_x=2, start_y=2, start_z=0)
    sm.set_screen(dungeon)

    dungeon.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP))

    assert not party.is_party_dead()
    assert sm.current_screen is dungeon
    # One consumed dungeon turn: −2 starvation, no heal, no mana regen.
    assert party.get_member(1).hp == 4
    assert all(m.food == 0 for m in party.members)


def test_overworld_chest_gas_trap_wipe_transitions_to_start_screen(sm, asset_mgr, monkeypatch):
    """A gas trap that kills the whole party (Task 1 pipeline) routes to game over."""

    class _FakeRandom:
        def randrange(self, n: int) -> int:  # trap hits, evade fails, trap #3 = gas
            return {2: 0, 100: 99, 4: 3, 50: 0, 8: 0, 32: 31}[n]

    import py_exodus.world.chests as chests_mod

    monkeypatch.setattr(chests_mod, "random", _FakeRandom())

    party = single_member_party(hp=10)
    # Fix round 2 (final): G opens the chest at the PARTY'S OWN TILE
    # (SIP x/y is the unshifted per-event copy; arrows never reach getChest).
    party.dynamic_objects.append({"tile": "chest", "x": party.x, "y": party.y})
    ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr, manager=sm)
    sm.set_screen(ow)

    from py_exodus.screens.start import StartScreen

    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_g, unicode="g"))
    assert ow.text_log.is_waiting_for_input
    ow.text_log.handle_char("1")
    ow.text_log.handle_enter()

    assert any("Gas Trap!" in line for line in ow.text_log.history)
    assert party.is_party_dead()
    assert isinstance(sm.current_screen, StartScreen)
    assert sm.current_screen.game_over is True


def test_dungeon_pit_trap_wipe_transitions_to_start_screen(sm, asset_mgr):
    """A dungeon pit trap killing the whole party routes to game over.

    Java truth: the pit applies TileEffect.LAVA (1-in-2 per member, 16+
    rand(32) damage); the stubbed RNG makes every roll hit so the wipe is
    deterministic.
    """
    dmap = DungeonMap(id=99, name="TestDungeon", width=16, height=16, levels=8)
    tiles = []
    for z in range(8):
        grid = []
        for y in range(16):
            row = []
            for x in range(16):
                if x == 0 or x == 15 or y == 0 or y == 15:
                    row.append(DungeonTile.WALL)
                else:
                    row.append(DungeonTile.FLOOR)
            grid.append(row)
        tiles.append(grid)
    dmap.tiles = tiles
    dmap.level_texts = ["" for _ in range(8)]
    dmap.set_tile(8, 7, 0, DungeonTile.PIT_TRAP)

    party = single_member_party(hp=10)
    dungeon = DungeonScreen(
        party=party,
        dungeon_map=dmap,
        asset_mgr=asset_mgr,
        start_x=8,
        start_y=8,
        start_dir=Direction.NORTH,
        manager=sm,
    )
    sm.set_screen(dungeon)
    # Java rand.nextInt(2) == 0 on every roll: the LAVA effect always fires
    # and 16 + rand(32)==0 == 16 damage kills the 10 hp member.
    dungeon.state.rng = _AlwaysHitRng()

    dungeon.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP))

    assert party.is_party_dead()
    from py_exodus.screens.start import StartScreen

    assert isinstance(sm.current_screen, StartScreen)
    assert sm.current_screen.game_over is True


def test_dungeon_fountain_acid_death_transitions_to_start_screen(sm, asset_mgr):
    """Dungeon acid fountain killing the whole party routes to game over."""
    dmap = DungeonMap(id=99, name="TestDungeon", width=16, height=16, levels=8)
    tiles = []
    for z in range(8):
        grid = []
        for y in range(16):
            row = []
            for x in range(16):
                if x == 0 or x == 15 or y == 0 or y == 15:
                    row.append(DungeonTile.WALL)
                else:
                    row.append(DungeonTile.FLOOR)
            grid.append(row)
        tiles.append(grid)
    dmap.tiles = tiles
    dmap.level_texts = ["" for _ in range(8)]
    dmap.set_tile(8, 8, 0, DungeonTile.FOUNTAIN_ACID)

    party = single_member_party(hp=10)
    dungeon = DungeonScreen(
        party=party,
        dungeon_map=dmap,
        asset_mgr=asset_mgr,
        start_x=8,
        start_y=8,
        start_dir=Direction.NORTH,
        manager=sm,
    )
    sm.set_screen(dungeon)

    dungeon.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_s, unicode="s"))
    assert dungeon.text_log.is_waiting_for_input
    dungeon.text_log.handle_char("1")
    dungeon.text_log.handle_enter()

    assert party.is_party_dead()
    from py_exodus.screens.start import StartScreen

    assert isinstance(sm.current_screen, StartScreen)
    assert sm.current_screen.game_over is True


def test_town_chest_gas_trap_wipe_transitions_to_start_screen(sm, asset_mgr, monkeypatch):
    """A town chest gas trap killing the whole party routes to game over."""

    class _FakeRandom:
        def randrange(self, n: int) -> int:
            return {2: 0, 100: 99, 4: 3, 50: 0, 8: 0, 32: 31}[n]

    import py_exodus.world.chests as chests_mod

    monkeypatch.setattr(chests_mod, "random", _FakeRandom())

    party = single_member_party(hp=10)
    # Fix round 2 (final): G opens the chest at the party's own tile.
    party.dynamic_objects.append({"tile": "chest", "x": 10, "y": 10})
    from py_exodus.screens.town import TownScreen

    town = TownScreen(
        party=party, map_id=1, asset_mgr=asset_mgr, start_x=10, start_y=10, manager=sm
    )
    sm.set_screen(town)

    from py_exodus.screens.start import StartScreen

    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_g, unicode="g"))
    assert town.text_log.is_waiting_for_input
    town.text_log.handle_char("1")
    town.text_log.handle_enter()

    assert party.is_party_dead()
    assert isinstance(sm.current_screen, StartScreen)
    assert sm.current_screen.game_over is True


def test_combat_defeat_transitions_to_start_screen_without_revival(sm, asset_mgr):
    """Combat defeat is a loss: StartScreen game over, no castle respawn/revive
    (Java GameScreen.java:433-446, CombatScreen.java:562-589)."""
    from py_exodus.world.loader import MapLoader

    loader = MapLoader(asset_mgr)
    c_map = loader.load_conflict_map("CNFLCT_B.ULT")

    before_map_id = 0
    party = single_member_party(hp=10)
    party.map_id = before_map_id

    combat = CombatScreen(
        party=party,
        combat_map=c_map,
        creature_tile="orc",
        asset_mgr=asset_mgr,
        return_screen=None,
        manager=sm,
    )
    sm.push_screen(combat)

    party.kill_all()
    combat.arena.is_defeat = True
    combat.arena.is_finished = True

    combat.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))

    from py_exodus.screens.start import StartScreen

    assert isinstance(sm.current_screen, StartScreen)
    assert sm.current_screen.game_over is True
    # No auto-revive and no Castle British warp
    assert party.is_party_dead()
    assert party.map_id == before_map_id
    assert all(m.status == Status.DEAD for m in party.members)
