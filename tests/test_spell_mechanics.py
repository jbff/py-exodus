"""Tests for APPAR_UNEM auto-collect and free combat spell limits."""
import pytest
from py_exodus.assets import AssetManager
from py_exodus.constants import Direction, Profession, Race, Spell, Status, Transport
from py_exodus.combat.magic import cast_spell
from py_exodus.combat.arena import CombatArena
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.world.dungeon import DungeonEventType, DungeonState
from py_exodus.world.map import DungeonMap, DungeonTile
from py_exodus.world.loader import MapLoader


@pytest.fixture
def asset_mgr():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


@pytest.fixture
def cleric_party():
    c1 = Character("Father Bob", "M", Race.HUMAN, Profession.CLERIC, mp=50, hp=100)
    c2 = Character("Friar Tuck", "M", Race.HUMAN, Profession.CLERIC, mp=50, hp=100)
    party = Party([PartyMember(c1), PartyMember(c2)], x=10, y=10, gold=100)
    return party


def test_appar_unem_overworld_dynamic_chest(cleric_party):
    """APPAR_UNEM removes dynamic chest and awards gold automatically without Get."""
    cleric_party.dynamic_objects.append({"tile": "chest", "x": 10, "y": 10})
    initial_gold = cleric_party.gold

    res = cast_spell(
        spell=Spell.APPAR_UNEM,
        caster=cleric_party.members[0],
        party=cleric_party,
    )

    assert res.success
    assert len(cleric_party.dynamic_objects) == 0
    assert cleric_party.gold > initial_gold
    assert "disarms and opens the chest" in res.message


def test_appar_unem_town_chest_tile(asset_mgr, cleric_party):
    """APPAR_UNEM in town replaces chest tile with floor and awards gold."""
    loader = MapLoader(asset_mgr)
    town_map = loader.load_map(1)  # Britain or similar

    # Place a chest tile adjacent to party
    px, py = cleric_party.x, cleric_party.y
    chest_tile = asset_mgr.get_tile_by_name("chest") or asset_mgr.get_tile_by_index(64)
    assert chest_tile is not None
    town_map.set_tile(px + 1, py, chest_tile)

    initial_gold = cleric_party.gold
    res = cast_spell(
        spell=Spell.APPAR_UNEM,
        caster=cleric_party.members[0],
        party=cleric_party,
        world_map=town_map,
    )

    assert res.success
    assert cleric_party.gold > initial_gold
    # Tile at px+1, py should no longer be a chest
    new_tile = town_map.get_tile(px + 1, py)
    assert new_tile.name != "chest"


def test_appar_unem_dungeon_chest(cleric_party):
    """APPAR_UNEM in dungeon opens chest disarmed and gives gold without taking damage."""
    dmap = DungeonMap(id=99, name="TestDungeon", width=16, height=16, levels=8)
    tiles = [[[DungeonTile.FLOOR for _ in range(16)] for _ in range(16)] for _ in range(8)]
    dmap.tiles = tiles
    state = DungeonState(dmap, start_x=2, start_y=2, start_z=0, party=cleric_party)
    dmap.set_tile(2, 2, 0, DungeonTile.CHEST)

    initial_gold = cleric_party.gold
    initial_hp = cleric_party.members[0].hp

    res = cast_spell(
        spell=Spell.APPAR_UNEM,
        caster=cleric_party.members[0],
        party=cleric_party,
        world_map=state,
    )

    assert res.success
    assert cleric_party.gold > initial_gold
    assert cleric_party.members[0].hp == initial_hp
    assert dmap.get_tile(2, 2, 0) == DungeonTile.NOTHING


def test_free_combat_spell_limits(asset_mgr, cleric_party):
    """PONTORI and REPOND are limited to 1 free cast per caster per combat engagement."""
    loader = MapLoader(asset_mgr)
    cmap = loader.load_conflict_map(41)

    arena = CombatArena(
        party=cleric_party,
        combat_map=cmap,
        creature_tile="skeleton",
        asset_mgr=asset_mgr,
        monster_count=2,
    )

    caster1 = cleric_party.members[0]
    caster2 = cleric_party.members[1]

    # First cast of PONTORI by caster1 succeeds
    res1 = cast_spell(
        spell=Spell.PONTORI,
        caster=caster1,
        arena=arena,
        party=cleric_party,
    )
    assert res1.success

    # Second cast of PONTORI by caster1 fails with "Can't!"
    res2 = cast_spell(
        spell=Spell.PONTORI,
        caster=caster1,
        arena=arena,
        party=cleric_party,
    )
    assert not res2.success
    assert "Can't!" in res2.message

    # Caster 2 has not used their free spell yet, so caster2 can still cast
    res3 = cast_spell(
        spell=Spell.PONTORI,
        caster=caster2,
        arena=arena,
        party=cleric_party,
    )
    assert res3.success

    # In a new combat encounter, free spell is reset
    arena2 = CombatArena(
        party=cleric_party,
        combat_map=cmap,
        creature_tile="skeleton",
        asset_mgr=asset_mgr,
        monster_count=1,
    )
    res4 = cast_spell(
        spell=Spell.PONTORI,
        caster=caster1,
        arena=arena2,
        party=cleric_party,
    )
    assert res4.success
