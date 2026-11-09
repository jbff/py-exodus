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
    test_party.aura.set(AuraType.QUICKNESS, 1)
    cr = CreatureDef(id=10, name="Orc", tile="orc", basehp=30, level=1)
    state.wandering_creatures.append(WanderingCreature(cr, 5, 3, 0))
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
