"""Dungeon doors, gremlins, chests, the dungeon tick (Task 13).

Java's wandering dungeon monsters were replaced by LairWare's per-command
encounter roll (batch D, tests/test_lw_parity_dungeon.py).

Java truth:
- ``exodus/DungeonScreen.java:1124-1142`` — finishTurn: creatureCleanup, the
  wandering spawn roll (``32 - currentLevel*2``, capped at
  ``Constants.MAX_WANDERING_CREATURES_IN_DUNGEON = 2``), then
  ``moveDungeonCreatures`` (path toward the avatar, battle on contact).
- ``exodus/DungeonScreen.java:1255-1330`` — spawn picks a random
  creature-walkable tile (10 tries) and ``CreatureSet.getRandomDungeonInstance``
  (level > 0, level <= currentLevel + 1, no sail/swim/good/wontattack).
- ``exodus/DungeonScreen.java:1054-1103`` — the dungeon block set is WALL plus
  FIELD_ENERGY; doors pass and GREMLINS logs "Gremlins!" and applies
  ``Party.applyEffect(GREMLINS)`` (Party.java:279-283 + 347-352: food -2 per
  non-DEAD member, no party-level die). Tasks 5-7 carry the port's GBC-rule
  deviations on top of this Java truth (see the deviation comments below).
- ``exodus/Context.java:248-285`` + ``Party.java:273-277`` — the chest trap
  (50% chance, dex evade, Acid/Gas/Poison) and ``rand(50) + rand(8) + 10``
  gold credited to the opening member.
"""
import random

import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.constants import Direction, Status
from py_exodus.entities.character import Character
from py_exodus.entities.defs import CreatureDef
from py_exodus.entities.party import Party
from py_exodus.world.dungeon import DungeonEventType, DungeonState
from py_exodus.world.map import DungeonMap, DungeonTile


@pytest.fixture
def asset_mgr():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


@pytest.fixture
def test_party():
    from py_exodus.constants import Profession, Race

    p = Party(food=200, gold=0)
    c1 = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, hp=100, max_hp=100, torches=5)
    c2 = Character("Mage", "F", Race.ELF, Profession.WIZARD, hp=80, max_hp=80, torches=0)
    p.add_member(c1)
    p.add_member(c2)
    return p


@pytest.fixture
def open_dmap():
    """16x16x8 dungeon with every tile open FLOOR (no walls)."""
    dmap = DungeonMap(id=98, name="OpenDungeon", width=16, height=16, levels=8)
    dmap.tiles = [
        [[(DungeonTile.FLOOR) for x in range(16)] for y in range(16)] for z in range(8)
    ]
    return dmap


class StubAssets:
    """Minimal asset_manager stand-in exposing a creature pool."""

    def __init__(self, *defs: CreatureDef) -> None:
        self.creatures = {}
        for cr in defs:
            self.creatures[cr.tile] = cr


class ZeroRNG(random.Random):
    """RNG whose randrange always returns 0 (spawn roll succeeds, picks (0,0))."""

    def randrange(self, *args, **kwargs):  # noqa: D401
        return 0


# --- Doors passable (DungeonScreen.java:1054-1056 block set) ---


def test_locked_and_secret_doors_passable(open_dmap):
    for tile in (DungeonTile.LOCKED_DOOR, DungeonTile.SECRET_DOOR):
        open_dmap.set_tile(5, 4, 0, tile)
        state = DungeonState(
            open_dmap,
            start_x=5,
            start_y=5,
            start_z=0,
            start_dir=Direction.NORTH,
            random_encounters=False,
        )
        ev = state.move_forward()
        assert ev.type == DungeonEventType.MOVED, tile
        assert state.x == 5 and state.y == 4


# --- Orbs removed entirely (Kept-Divergence #2) ---


def test_orbs_removed(open_dmap, test_party):
    state = DungeonState(open_dmap, start_x=5, start_y=5, start_z=0, party=test_party)
    assert not hasattr(state, "touch_orb")
    assert "ORB" not in [e.name for e in DungeonEventType]


def test_dungeon_orb_tile_never_mentions_orbs(asset_mgr, open_dmap, test_party):
    """A command on an ORB tile gives no orb prompt or line (S is no longer
    a dungeon command, LW D-12)."""
    from py_exodus.screens.dungeon_screen import DungeonScreen

    pygame.init()
    open_dmap.set_tile(5, 5, 0, DungeonTile.ORB)
    screen = DungeonScreen(party=test_party, dungeon_map=open_dmap, asset_mgr=asset_mgr)
    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_s))
    screen.text_log.handle_event(
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1, unicode="1")
    )
    joined = "\n".join(screen.text_log.lines)
    assert "Magical Orb" not in joined
    assert "orb" not in joined.lower()


# --- Gremlins: USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): gremlins
# --- drain 100 food from one member (GBC dungfunc.c:1177-1189; LW
# --- corroborates) — supersedes the Java -2-per-member fan-out.


class _SlotRng:
    """randint always returns ``slot``: a deterministic gremlin slot."""

    def __init__(self, slot: int) -> None:
        self.slot = slot

    def randint(self, a: int, b: int) -> int:
        return min(max(self.slot, a), b)

    def randrange(self, n: int) -> int:
        return 0


def _gremlin_state(open_dmap, test_party, slot):
    open_dmap.set_tile(5, 4, 0, DungeonTile.GREMLINS)
    return DungeonState(
        open_dmap, start_x=5, start_y=5, start_z=0, start_dir=Direction.NORTH,
        party=test_party, rng=_SlotRng(slot), random_encounters=False,
    )


def test_gremlins_take_a_hundreds_from_the_slot(open_dmap, test_party):
    """LairWare gremlins (UltimaDngn.c:319-333, ledger D-14): the slot's
    hundreds of food drop by one; under 100 nothing is lost."""
    test_party.members[0].food = 90
    test_party.members[1].food = 110
    ev = _gremlin_state(open_dmap, test_party, 0).move_forward()
    assert ev.type == DungeonEventType.GREMLINS
    assert test_party.members[0].food == 90  # hundreds byte already 0
    assert test_party.members[1].food == 110  # untouched
    assert open_dmap.get_tile(5, 4, 0) == DungeonTile.NOTHING


def test_gremlins_at_a_dead_slot_take_nothing(open_dmap, test_party):
    """CheckAlive false (UltimaDngn.c:322-323): a dead member's slot ends the
    gremlins' visit; the living member keeps its food too."""
    from py_exodus.constants import Status

    test_party.members[0].food = 190
    test_party.members[1].food = 110
    test_party.members[0].status = Status.DEAD
    _gremlin_state(open_dmap, test_party, 0).move_forward()
    assert test_party.members[0].food == 190
    assert test_party.members[1].food == 110


# --- Creature pool: level defaults 0, excluded from dungeon instances ---


def test_creature_def_default_level_zero():
    cr = CreatureDef(id=1, name="Fighter", tile="fighter", basehp=96)
    assert cr.level == 0


def test_xml_creatures_without_level_default_zero(asset_mgr):
    assert asset_mgr.creatures["fighter"].level == 0
    assert asset_mgr.creatures["wizard"].level == 0
    assert asset_mgr.creatures["orc"].level == 1


def test_dungeon_tick_drains_food_and_never_ticks_moves(open_dmap, test_party):
    """Pending item 23 (USER-DIRECTED GBC-RULES DEVIATION, 2026-11-14): the
    dungeon tick runs the per-member meal pipeline at the underground
    cadence (GBC funcs5.c:1274; LW UltimaMisc.c:1428-1467 corroborates) —
    45 calls are 12 ticks of 40: the 400 pool crosses once (tick 11), the
    residual carried (LairWare EatFood, UltimaMisc.c:1472-1474) —
    while ``Party.endTurn`` is still never called: the move counter stays
    put (Java DungeonScreen.finishTurn, DungeonScreen.java:1124-1142)."""
    state = DungeonState(
        open_dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        party=test_party,
        rng=ZeroRNG(),
        random_encounters=False,
    )
    m = test_party.members[0]
    m.submorsels = 400
    m.food = 90
    moves_before = test_party.moves
    for _ in range(45):  # ticks on calls 1, 5, ..., 45: 12 ticks
        state._tick_turn()
    assert m.submorsels == 400 - 12 * 40 + 396
    assert m.food == 89
    assert test_party.moves == moves_before


def test_dungeon_tick_regens_mana_and_ticks_meals(open_dmap, test_party):
    """LairWare dungeonmech (UltimaDngn.c:183-189) runs AgeChars after every
    dungeon command, acting every 4th call (ledger D-01): 4 commands make
    one tick (the first), +1 MP and 40 of the pool; no crossing, no heal
    (that is the 10th tick), no food spent."""
    state = DungeonState(
        open_dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        party=test_party,
        rng=ZeroRNG(),
        random_encounters=False,
    )
    hero = test_party.members[0]
    mage = test_party.members[1]
    hero.hp = 50
    mage.mp = 0
    food_before = test_party.food
    for _ in range(4):
        state._tick_turn()
    assert hero.hp == 50  # one tick: no heal before the 10th
    assert mage.mp == 1  # +1 mana on the one tick
    assert hero.submorsels == 360  # one tick of 40
    assert test_party.food == food_before  # no crossing → no food spent


def test_dungeon_tick_does_not_count_stopped_time_down(open_dmap, test_party):
    """LairWare reads gTimeNegate only in FinishAll (UltimaMisc.c:1120-1123)
    and in combat; a dungeon command runs neither (dungeonmech,
    UltimaDngn.c:183-209), so stopped time keeps its count underground
    (ledger T-13)."""
    from py_exodus.aura import AuraType

    state = DungeonState(
        open_dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        party=test_party,
        rng=ZeroRNG(),
        random_encounters=False,
    )
    test_party.aura.set(AuraType.QUICKNESS, 1)
    state._tick_turn()
    assert test_party.aura.get_type() == AuraType.QUICKNESS
    assert test_party.aura.get_duration() == 1


def test_normal_move_no_direct_ambush_roll(open_dmap, test_party):
    """A move ends MOVED, or COMBAT when LairWare's encounter roll fires."""
    state = DungeonState(
        open_dmap,
        start_x=15,
        start_y=15,
        start_z=0,
        start_dir=Direction.NORTH,
        party=test_party,
        rng=ZeroRNG(),
    )
    ev = state.move_forward()
    assert ev.type in (DungeonEventType.MOVED, DungeonEventType.COMBAT)
    if ev.type == DungeonEventType.COMBAT:
        assert ev.creature is not None


# --- Dungeon chest parity (Context.java:248-285, Party.java:273-277) ---


def test_open_chest_fallback_message_matches_java(open_dmap, test_party):
    """Java DungeonScreen.getChest's fallback line is "Not Here!"
    (DungeonScreen.java:1247) — not an invented "No chest here!"."""
    state = DungeonState(
        open_dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        party=test_party,
    )
    open_dmap.set_tile(5, 5, 0, DungeonTile.FLOOR)
    evt = state.open_chest()
    assert evt.message == "Not Here!"
    assert not evt.success


def test_dungeon_chest_delegates_to_pipeline(open_dmap, test_party, monkeypatch):
    import py_exodus.world.chests as chests

    calls = []

    def fake_randrange(n, **kwargs):
        calls.append(n)
        return 1  # no trap; LW gold 1 + 30 = 31; gate open, weapon (1 & 1) & 7 = Dagger

    monkeypatch.setattr(chests, "random", type("M", (), {"randrange": staticmethod(fake_randrange)}))

    test_party.members[0].gold = 200
    open_dmap.set_tile(5, 5, 0, DungeonTile.CHEST)
    state = DungeonState(
        open_dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        party=test_party,
        random_encounters=False,
    )
    ev = state.open_chest(member_index=0, disarm=True)
    assert ev.type == DungeonEventType.CHEST
    assert ev.gold == 31
    assert test_party.members[0].gold == 231
    assert open_dmap.get_tile(5, 5, 0) == DungeonTile.NOTHING


def test_dungeon_chest_trapped_without_disarm(open_dmap, test_party, monkeypatch):
    import py_exodus.world.chests as chests

    # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): Gas trap poisons every
    # living member (GBC menucmd.c:1077-1147; LW UltimaMain.c:1718-1734 case
    # 3) — no damage rolls, both living members end POISONED at full HP.
    seq = [0, 99, 3, 3]

    def fake_randrange(n, **kwargs):
        return seq.pop(0) if seq else 0

    monkeypatch.setattr(chests, "random", type("M", (), {"randrange": staticmethod(fake_randrange)}))

    m0, m1 = test_party.members
    open_dmap.set_tile(5, 5, 0, DungeonTile.CHEST)
    state = DungeonState(
        open_dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        party=test_party,
        random_encounters=False,
    )
    ev = state.open_chest(member_index=0, disarm=False)
    assert ev.type == DungeonEventType.CHEST
    assert m0.status == Status.POISONED and m0.hp == m0.max_hp
    assert m1.status == Status.POISONED and m1.hp == m1.max_hp


def test_dungeon_chest_disarm_skips_trap(open_dmap, test_party, monkeypatch):
    import py_exodus.world.chests as chests

    monkeypatch.setattr(
        chests, "random", type("M", (), {"randrange": staticmethod(lambda n, **kw: 0)})
    )

    m0 = test_party.members[0]
    open_dmap.set_tile(5, 5, 0, DungeonTile.CHEST)
    state = DungeonState(
        open_dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        party=test_party,
        random_encounters=False,
    )
    ev = state.open_chest(member_index=0, disarm=True)
    assert ev.type == DungeonEventType.CHEST
    assert m0.hp == m0.max_hp  # untouched: the trap roll was skipped
    assert ev.gold == 30  # LW RandNum(0, 100) = 0 -> +30
    assert m0.gold == 150 + 30  # Character default purse + chest gold


# --- Combat exit: endCombat port (DungeonScreen.java:740-769) ---

def _dungeon_screen(open_dmap, test_party, asset_mgr):
    from py_exodus.screens.dungeon_screen import DungeonScreen

    pygame.init()
    # Avatar parked at (5,5) on level 0, matching the fixture coordinates.
    return DungeonScreen(
        party=test_party,
        dungeon_map=open_dmap,
        asset_mgr=asset_mgr,
        start_x=5,
        start_y=5,
        start_z=0,
    )


def test_combat_screen_notifies_return_screen(asset_mgr, open_dmap, test_party):
    """Java CombatScreen.end (CombatScreen.java:579-587): returnScreen.endCombat
    runs once when the battle is acknowledged as over."""
    from py_exodus.screens.combat_screen import CombatScreen
    from py_exodus.world.loader import MapLoader

    loader = MapLoader(asset_mgr)
    c_map = loader.load_conflict_map("cnflct_b.json")
    calls = []

    class Recorder:
        def end_combat(self, is_won):
            calls.append(is_won)

    pygame.init()
    scr = CombatScreen(
        party=test_party,
        combat_map=c_map,
        creature_tile="orc",
        asset_mgr=asset_mgr,
        return_screen=Recorder(),
    )
    scr.arena.is_finished = True
    scr.arena.is_victory = True
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    assert calls == [True]


# --- Minor: blocked dungeon moves still finishTurn (DungeonScreen.java:1052-1076) ---


def test_blocked_move_still_ticks(open_dmap, test_party):
    open_dmap.set_tile(5, 4, 0, DungeonTile.WALL)
    state = DungeonState(
        open_dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        start_dir=Direction.NORTH,
        party=test_party,
        rng=ZeroRNG(),
        random_encounters=False,
    )
    moves_before = test_party.moves
    test_party.members[0].submorsels = 400

    ev = state.move_forward()

    assert ev.type == DungeonEventType.BLOCKED
    # finishTurn runs on the blocked move but NEVER Party.endTurn
    # (DungeonScreen.java:1124-1141), so the move counter does not tick.
    assert test_party.moves == moves_before
    # The turn tick ran on the blocked move: AgeChars' first call acts
    # (gTime[0] starts at 0) and the meal pool moved by 40.
    assert test_party.members[0].submorsels == 360


