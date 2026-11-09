"""Dungeon wandering monsters, doors, creature pool, gremlins, chests (Task 13).

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
  non-DEAD member, no party-level die).
- ``exodus/Context.java:248-285`` + ``Party.java:273-277`` — the chest trap
  (50% chance, dex evade, Acid/Gas/Poison) and ``rand(50) + rand(8) + 10``
  gold credited to the opening member.
"""
import random

import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.constants import Direction
from py_exodus.entities.character import Character
from py_exodus.entities.defs import CreatureDef
from py_exodus.entities.party import Party
from py_exodus.world.dungeon import DungeonEventType, DungeonState, WanderingCreature
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


def test_dungeon_search_never_mentions_orbs(asset_mgr, open_dmap, test_party):
    """Searching an ORB tile falls to the generic search, no orb prompt/line."""
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


# --- Gremlins: Java Party.applyEffect fan-out (food -2 per member) ---


def test_gremlins_take_2_food_per_member(open_dmap, test_party):
    test_party.members[0].food = 90
    test_party.members[1].food = 110
    open_dmap.set_tile(5, 4, 0, DungeonTile.GREMLINS)
    state = DungeonState(
        open_dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        start_dir=Direction.NORTH,
        party=test_party,
        random_encounters=False,
    )
    ev = state.move_forward()
    assert ev.type == DungeonEventType.GREMLINS
    assert test_party.members[0].food == 88
    assert test_party.members[1].food == 108
    assert open_dmap.get_tile(5, 4, 0) == DungeonTile.NOTHING


def test_gremlins_dead_member_immune(open_dmap, test_party):
    from py_exodus.constants import Status

    test_party.members[0].food = 90
    test_party.members[1].food = 110
    test_party.members[1].status = Status.DEAD
    open_dmap.set_tile(5, 4, 0, DungeonTile.GREMLINS)
    state = DungeonState(
        open_dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        start_dir=Direction.NORTH,
        party=test_party,
        random_encounters=False,
    )
    state.move_forward()
    assert test_party.members[0].food == 88
    assert test_party.members[1].food == 110


# --- Creature pool: level defaults 0, excluded from dungeon instances ---


def test_creature_def_default_level_zero():
    cr = CreatureDef(id=1, name="Fighter", tile="fighter", basehp=96)
    assert cr.level == 0


def test_xml_creatures_without_level_default_zero(asset_mgr):
    assert asset_mgr.creatures["fighter"].level == 0
    assert asset_mgr.creatures["wizard"].level == 0
    assert asset_mgr.creatures["orc"].level == 1


def test_pool_excludes_zero_level_creatures(asset_mgr, open_dmap):
    state = DungeonState(
        open_dmap, start_x=5, start_y=5, start_z=0, asset_manager=asset_mgr
    )
    for _ in range(30):
        cr = state._pick_dungeon_creature()
        assert cr is not None
        assert cr.level > 0
        assert cr.level <= state.z + 1
        assert cr.tile not in ("fighter", "wizard")


def test_no_fallback_monsters_without_assets(open_dmap):
    state = DungeonState(open_dmap, start_x=5, start_y=5, start_z=0, asset_manager=None)
    assert state._pick_dungeon_creature() is None


def test_pool_respects_depth(open_dmap, asset_mgr):
    state = DungeonState(
        open_dmap, start_x=5, start_y=5, start_z=0, asset_manager=asset_mgr
    )
    state.z = 0  # dungeonLevel 1: only level-1 creatures
    for _ in range(30):
        cr = state._pick_dungeon_creature()
        assert cr.level == 1


# --- Wandering monsters (DungeonScreen.java:1255-1330) ---


def test_wandering_spawn_on_roll(open_dmap, test_party):
    state = DungeonState(
        open_dmap,
        start_x=15,
        start_y=15,
        start_z=0,
        party=test_party,
        rng=ZeroRNG(),
        asset_manager=StubAssets(
            CreatureDef(id=10, name="Orc", tile="orc", basehp=30, level=1)
        ),
    )
    state._tick_turn()
    assert len(state.wandering_creatures) == 1
    cr = state.wandering_creatures[0]
    assert cr.creature.level > 0
    assert cr.level == 0  # spawns on the avatar's level
    assert open_dmap.get_tile(cr.x, cr.y, cr.level).creature_walkable


def test_wandering_cap_two_per_level(open_dmap, test_party):
    state = DungeonState(
        open_dmap,
        start_x=15,
        start_y=15,
        start_z=0,
        party=test_party,
        rng=ZeroRNG(),
        asset_manager=StubAssets(
            CreatureDef(id=10, name="Orc", tile="orc", basehp=30, level=1)
        ),
    )
    state._tick_turn()
    state._tick_turn()
    state._tick_turn()
    assert len(state.wandering_creatures) == 2


def test_wandering_moves_toward_avatar(open_dmap, test_party):
    state = DungeonState(
        open_dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        party=test_party,
        rng=ZeroRNG(),
        random_encounters=False,
    )
    cr = CreatureDef(id=10, name="Orc", tile="orc", basehp=30, level=1)
    state.wandering_creatures.append(WanderingCreature(cr, 5, 3, 0))
    state._tick_turn()
    assert state.wandering_creatures[0].x == 5
    assert state.wandering_creatures[0].y == 4


def test_wandering_contact_battle(open_dmap, test_party):
    state = DungeonState(
        open_dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        party=test_party,
        rng=ZeroRNG(),
        random_encounters=False,
    )
    cr = CreatureDef(id=10, name="Orc", tile="orc", basehp=30, level=1)
    state.wandering_creatures.append(WanderingCreature(cr, 5, 4, 0))
    evt = state._tick_turn()
    assert evt is not None
    assert evt.type == DungeonEventType.COMBAT
    assert evt.creature is cr


def test_wandering_avoids_occupied_tiles(open_dmap, test_party):
    state = DungeonState(
        open_dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        party=test_party,
        rng=ZeroRNG(),
        random_encounters=False,
    )
    orc = CreatureDef(id=10, name="Orc", tile="orc", basehp=30, level=1)
    skele = CreatureDef(id=11, name="Skeleton", tile="skeleton", basehp=50, level=1)
    # Mover north of a second creature that blocks the only step south.
    state.wandering_creatures.append(WanderingCreature(orc, 5, 3, 0))
    state.wandering_creatures.append(WanderingCreature(skele, 5, 4, 0))
    state._tick_turn()
    mover = state.wandering_creatures[0]
    assert (mover.x, mover.y) == (5, 3)


def test_wandering_cleanup_on_level_change(open_dmap, test_party):
    state = DungeonState(
        open_dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        party=test_party,
        rng=ZeroRNG(),
        random_encounters=False,
    )
    cr = CreatureDef(id=10, name="Orc", tile="orc", basehp=30, level=1)
    state.wandering_creatures.append(WanderingCreature(cr, 5, 4, 3))
    state._tick_turn()
    assert state.wandering_creatures == []


def test_dungeon_tick_never_runs_party_end_turn(open_dmap, test_party):
    """Java DungeonScreen.finishTurn (1124-1142) runs aura.passTurn +
    creature upkeep ONLY — Party.endTurn is never called in dungeons, so no
    submorsel drain, food loss or move-counter increment per dungeon move."""
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
    m.submorsels = 10
    m.food = 90
    moves_before = test_party.moves
    for _ in range(45):  # 45 x 10-drain ticks would have crossed twice
        state._tick_turn()
    assert m.submorsels == 10
    assert m.food == 90
    assert test_party.moves == moves_before


def test_dungeon_tick_passes_the_aura_turn(open_dmap, test_party):
    """Java finishTurn opens with getAura().passTurn() — a dungeon move
    decrements the aura (and expires it at 0) like any other screen."""
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
    assert not test_party.aura.is_active()
    assert test_party.aura.get_type() == AuraType.NONE


def test_quickness_holds_wandering_movement(open_dmap, test_party):
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
    # Java order (DungeonScreen.finishTurn): passTurn runs BEFORE the
    # quickness check, so an aura with 1 turn left expires without holding
    # this turn's creature movement.
    test_party.aura.set(AuraType.QUICKNESS, 1)
    cr = CreatureDef(id=10, name="Orc", tile="orc", basehp=30, level=1)
    state.wandering_creatures.append(WanderingCreature(cr, 5, 3, 0))
    state._tick_turn()
    assert (state.wandering_creatures[0].x, state.wandering_creatures[0].y) == (5, 4)

    # A fresh turn of quickness still freezes the wanderers for the turn.
    test_party.aura.set(AuraType.QUICKNESS, 2)
    cr2 = CreatureDef(id=11, name="Skeleton", tile="skeleton", basehp=50, level=1)
    state.wandering_creatures = [WanderingCreature(cr2, 5, 3, 0)]
    state._tick_turn()
    assert (state.wandering_creatures[0].x, state.wandering_creatures[0].y) == (5, 3)


def test_normal_move_no_direct_ambush_roll(open_dmap, test_party):
    """The old invented ambush roll is gone: MOVED unless a wandering creature
    actually reaches the avatar."""
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


def test_minimap_marks_wandering_creatures(open_dmap, test_party, asset_mgr):
    """Each wandering creature on the visible level draws a marker dot on
    the minimap; creatures on other levels do not."""
    from py_exodus.screens.dungeon_screen import DungeonScreen
    from py_exodus.ui.text_log import EGA_YELLOW

    pygame.init()
    screen = DungeonScreen(
        party=test_party, dungeon_map=open_dmap, asset_mgr=asset_mgr
    )
    cr = CreatureDef(id=10, name="Orc", tile="orc", basehp=30, level=1)
    screen.state.wandering_creatures.append(WanderingCreature(cr, 6, 7, 0))
    off_level = CreatureDef(id=11, name="Skeleton", tile="skeleton", basehp=50, level=1)
    screen.state.wandering_creatures.append(WanderingCreature(off_level, 8, 8, 1))

    target = pygame.Surface((96, 96))
    screen._render_minimap(target)

    cell = 4
    offset_x = target.get_width() - open_dmap.width * cell - 4
    offset_y = 20
    assert (
        target.get_at((offset_x + 6 * cell + 1, offset_y + 7 * cell + 1))[:3]
        == EGA_YELLOW
    )
    # The off-level creature draws nothing (cell would stay floor-gray).
    assert (
        target.get_at((offset_x + 8 * cell + 1, offset_y + 8 * cell + 1))[:3]
        != EGA_YELLOW
    )


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
        return 1  # no trap; gold 1+1+10 = 12

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
    assert ev.gold == 12
    assert test_party.members[0].gold == 212
    assert open_dmap.get_tile(5, 5, 0) == DungeonTile.NOTHING


def test_dungeon_chest_trapped_without_disarm(open_dmap, test_party, monkeypatch):
    import py_exodus.world.chests as chests

    # hasTrap roll 0 → trap; evade roll 99 (dex+25 < 99 fails); gas trap
    # (whichTrap 3); lava damage 16 + rand(32)=0 → 16 per non-DEAD member.
    seq = [0, 99, 3, 0]

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
    assert m0.hp == m0.max_hp - 16
    assert m1.hp == m1.max_hp - 16


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
    assert ev.gold == 10
    assert m0.gold == 150 + 10  # Character default purse + chest gold


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


def test_combat_event_carries_the_wanderer(open_dmap, test_party):
    state = DungeonState(
        open_dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        party=test_party,
        rng=ZeroRNG(),
        random_encounters=False,
    )
    cr = CreatureDef(id=10, name="Orc", tile="orc", basehp=30, level=1)
    state.wandering_creatures.append(WanderingCreature(cr, 5, 4, 0))
    evt = state._tick_turn()
    assert evt.type == DungeonEventType.COMBAT
    assert evt.wandering is state.wandering_creatures[0]


def test_end_combat_removes_encounter_creature(open_dmap, test_party, asset_mgr):
    screen = _dungeon_screen(open_dmap, test_party, asset_mgr)
    cr = CreatureDef(id=10, name="Orc", tile="orc", basehp=30, level=1)
    wc = WanderingCreature(cr, 6, 5, 0)
    screen.state.wandering_creatures.append(wc)
    screen._trigger_combat("orc", encounter=wc)

    screen.end_combat(True)
    assert wc not in screen.state.wandering_creatures
    assert screen.current_encounter is None

    # Losing/fleeing removes the encounter too (Java removes unconditionally).
    screen.state.wandering_creatures.append(wc)
    screen._trigger_combat("orc", encounter=wc)
    screen.end_combat(False)
    assert wc not in screen.state.wandering_creatures


def test_end_combat_releases_wandering_softlock(open_dmap, test_party, asset_mgr):
    screen = _dungeon_screen(open_dmap, test_party, asset_mgr)
    cr = CreatureDef(id=10, name="Orc", tile="orc", basehp=30, level=1)
    wc = WanderingCreature(cr, 5, 4, 0)  # adjacent: would re-battle forever
    screen.state.wandering_creatures.append(wc)
    screen._trigger_combat("orc", encounter=wc)

    screen.end_combat(True)
    # Ticks no longer re-trigger: the creature is gone from the level.
    assert screen.state._tick_turn() is None


def test_end_combat_win_drops_chest_on_avatar_tile(open_dmap, test_party, asset_mgr):
    screen = _dungeon_screen(open_dmap, test_party, asset_mgr)
    assert open_dmap.get_tile(5, 5, 0) == DungeonTile.FLOOR
    # Java drops the chest only onto a NOTHING tile.
    open_dmap.set_tile(5, 5, 0, DungeonTile.NOTHING)
    cr = CreatureDef(id=10, name="Orc", tile="orc", basehp=30, level=1)
    wc = WanderingCreature(cr, 6, 5, 0)
    screen.state.wandering_creatures.append(wc)
    screen._trigger_combat("orc", encounter=wc)

    screen.end_combat(True)
    assert open_dmap.get_tile(5, 5, 0) == DungeonTile.CHEST

    # A creature with nochest leaves no chest.
    open_dmap.set_tile(5, 5, 0, DungeonTile.NOTHING)
    cr2 = CreatureDef(id=12, name="Thief", tile="thief", basehp=80, level=3, no_chest=True)
    wc2 = WanderingCreature(cr2, 6, 5, 0)
    screen.state.wandering_creatures.append(wc2)
    screen._trigger_combat("thief", encounter=wc2)
    screen.end_combat(True)
    assert open_dmap.get_tile(5, 5, 0) == DungeonTile.NOTHING


def test_end_combat_loss_drops_no_chest(open_dmap, test_party, asset_mgr):
    screen = _dungeon_screen(open_dmap, test_party, asset_mgr)
    open_dmap.set_tile(5, 5, 0, DungeonTile.NOTHING)
    cr = CreatureDef(id=10, name="Orc", tile="orc", basehp=30, level=1)
    wc = WanderingCreature(cr, 6, 5, 0)
    screen.state.wandering_creatures.append(wc)
    screen._trigger_combat("orc", encounter=wc)

    screen.end_combat(False)
    assert open_dmap.get_tile(5, 5, 0) == DungeonTile.NOTHING


def test_combat_screen_notifies_return_screen(asset_mgr, open_dmap, test_party):
    """Java CombatScreen.end (CombatScreen.java:579-587): returnScreen.endCombat
    runs once when the battle is acknowledged as over."""
    from py_exodus.screens.combat_screen import CombatScreen
    from py_exodus.world.loader import MapLoader

    loader = MapLoader(asset_mgr)
    c_map = loader.load_conflict_map("CNFLCT_B.ULT")
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
    cr = CreatureDef(id=10, name="Orc", tile="orc", basehp=30, level=1)
    state.wandering_creatures.append(WanderingCreature(cr, 3, 5, 0))
    moves_before = test_party.moves

    ev = state.move_forward()

    assert ev.type == DungeonEventType.BLOCKED
    # finishTurn runs on the blocked move but NEVER Party.endTurn
    # (DungeonScreen.java:1124-1141), so the move counter does not tick.
    assert test_party.moves == moves_before
    # finishTurn ran on the blocked move: the wanderer advanced toward the avatar.
    assert (state.wandering_creatures[0].x, state.wandering_creatures[0].y) == (4, 5)


def test_blocked_move_can_trigger_battle(open_dmap, test_party):
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
    # Creature adjacent east of the avatar (north is walled).
    cr = CreatureDef(id=10, name="Orc", tile="orc", basehp=30, level=1)
    state.wandering_creatures.append(WanderingCreature(cr, 4, 5, 0))

    ev = state.move_forward()
    assert ev.type == DungeonEventType.COMBAT
    assert ev.creature is cr
    assert ev.wandering is state.wandering_creatures[0]


# --- Minor: no toward-direction means no battle check (Utils.getPath null) ---


def test_creature_with_no_toward_direction_skips_battle(open_dmap, test_party):
    """Creature spawned on the avatar's tile: getPath returns null (it is
    already there) and Java skips the contact check — no battle, the creature
    stays put (DungeonScreen.java:1300-1302 continue)."""
    state = DungeonState(
        open_dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        party=test_party,
        rng=ZeroRNG(),
        random_encounters=False,
    )
    cr = CreatureDef(id=10, name="Orc", tile="orc", basehp=30, level=1)
    wc = WanderingCreature(cr, 5, 5, 0)
    state.wandering_creatures.append(wc)

    for _ in range(3):
        assert state._tick_turn() is None
    assert (wc.x, wc.y) == (5, 5)


# --- Fix round 2: merged (blocked-move) battle path carries the wanderer ---


def test_blocked_move_battle_keeps_encounter_and_ends_cleanly(
    open_dmap, test_party, asset_mgr
):
    """r1 hole: `_with_combat` dropped the `wandering` field on the six merged
    paths, so blocked-move battles raised with encounter=None and end_combat
    removed nothing. Java battleWandering always keeps the creature until
    endCombat removes it (DungeonScreen.java:724-737, 767-769)."""
    screen = _dungeon_screen(open_dmap, test_party, asset_mgr)
    # The wandering SPAWN roll (self.rng.randrange(32), DungeonScreen.java
    # finishTurn) is orthogonal to what this test asserts — the pre-placed
    # wanderer that the blocked move must merge. With DungeonScreen's live
    # state (random_encounters on by default and an unseeded RNG seeded from
    # os.urandom per construction) a 1-in-32 spawn on any of the four ticks
    # below leaves a stray creature after end_combat (which removes only the
    # encounter creature) or drops a fresh one into the closing move loop,
    # failing assertions that the spawn roll itself never controlled. Pin
    # both dials: spawn off (matching the file's other DungeonState tests)
    # and a seeded rng for the contact-direction roll, so the test's own
    # assertions stay exact.
    screen.state.random_encounters_enabled = False
    screen.state.rng = random.Random(7)

    open_dmap.set_tile(5, 4, 0, DungeonTile.WALL)  # the forward move blocks
    open_dmap.set_tile(5, 5, 0, DungeonTile.NOTHING)  # chest-eligible tile
    cr = CreatureDef(id=10, name="Orc", tile="orc", basehp=30, level=1)
    screen.state.wandering_creatures.append(WanderingCreature(cr, 4, 5, 0))

    ev = screen.state.move_forward()
    assert ev.type == DungeonEventType.COMBAT
    assert ev.wandering is not None  # the merged event carries the wanderer

    screen._process_event(ev)
    assert screen.current_encounter is ev.wandering

    screen.end_combat(True)
    assert screen.state.wandering_creatures == []
    assert open_dmap.get_tile(5, 5, 0) == DungeonTile.CHEST

    # No re-trigger on following ticks (the soft-lock stays dead).
    for _ in range(3):
        assert screen.state.move_forward().type != DungeonEventType.COMBAT
