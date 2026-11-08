"""Tests for APPAR_UNEM chest pipeline (Java GameScreen.getChest
/ DungeonScreen.getChest with disarmed=true) and the dungeon spells
(Java SpellUtil.spellYup/spellZdown/spellLibRec/spellXit)."""
import pytest
from py_exodus.assets import AssetManager
from py_exodus.constants import Direction, Profession, Race, Spell, Status, Transport
from py_exodus.combat.magic import cast_spell
from py_exodus.combat.arena import CombatArena
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.world.dungeon import DungeonState
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


# --- APPAR_UNEM requires a direction (Java SpellUtil.java:40-50) ---

def test_appar_unem_requires_direction(cleric_party):
    res = cast_spell(
        spell=Spell.APPAR_UNEM,
        caster=cleric_party.members[0],
        party=cleric_party,
    )
    assert not res.success
    assert "indicate a direction" in res.message
    assert cleric_party.members[0].mp == 50


def test_appar_unem_overworld_dynamic_chest(cleric_party):
    """APPAR_UNEM opens the chest at the party's own tile (Java getChest scans
    exactly cx == x && cy == y) and awards gold through the Task 1 pipeline.
    The direction is prompted but ignored (SpellUtil.java:140-148)."""
    cleric_party.dynamic_objects.append({"tile": "chest", "x": 10, "y": 10})
    initial_gold = cleric_party.gold
    initial_hp = cleric_party.members[0].hp

    res = cast_spell(
        spell=Spell.APPAR_UNEM,
        caster=cleric_party.members[0],
        target_dir=Direction.NORTH,
        party=cleric_party,
    )

    assert res.success
    assert len(cleric_party.dynamic_objects) == 0
    assert cleric_party.gold > initial_gold  # rand(50)+rand(8)+10 credited
    assert "The Chest Holds" in res.message
    # disarmed=True — no trap ever fires
    assert cleric_party.members[0].hp == initial_hp


def test_appar_unem_world_chest_tile_at_party_position(asset_mgr, cleric_party):
    """GameScreen.getChest falls back to the chest *tile* under the party."""
    loader = MapLoader(asset_mgr)
    town_map = loader.load_map(1)

    px, py = cleric_party.x, cleric_party.y
    chest_tile = asset_mgr.get_tile_by_name("chest") or asset_mgr.get_tile_by_index(64)
    assert chest_tile is not None
    town_map.set_tile(px, py, chest_tile)

    initial_gold = cleric_party.gold
    initial_hp = cleric_party.members[0].hp
    res = cast_spell(
        spell=Spell.APPAR_UNEM,
        caster=cleric_party.members[0],
        target_dir=Direction.SOUTH,
        party=cleric_party,
        world_map=town_map,
    )

    assert res.success
    assert cleric_party.gold > initial_gold
    assert cleric_party.members[0].hp == initial_hp
    new_tile = town_map.get_tile(px, py)
    assert new_tile.name != "chest"


def test_appar_unem_world_no_chest_nearby(cleric_party):
    res = cast_spell(
        spell=Spell.APPAR_UNEM,
        caster=cleric_party.members[0],
        target_dir=Direction.WEST,
        party=cleric_party,
    )
    assert res.success is False
    assert "Not Here!" in res.message
    # The attempted cast still burns the spell's mana once validated — but no
    # chest means Java logs "Not Here!" after getChest is reached post-deduct.
    assert cleric_party.gold == 100


def test_appar_unem_dungeon_chest(cleric_party):
    """APPAR_UNEM in dungeon opens the chest on the party tile, disarmed,
    through the shared chests pipeline (DungeonScreen.getChest, disarmed)."""
    dmap = DungeonMap(id=99, name="TestDungeon", width=16, height=16, levels=8)
    tiles = [[[DungeonTile.NOTHING for _ in range(16)] for _ in range(16)] for _ in range(8)]
    dmap.tiles = tiles
    state = DungeonState(dmap, start_x=2, start_y=2, start_z=0, party=cleric_party)
    dmap.set_tile(2, 2, 0, DungeonTile.CHEST)

    initial_gold = cleric_party.gold
    initial_hp = cleric_party.members[0].hp

    res = cast_spell(
        spell=Spell.APPAR_UNEM,
        caster=cleric_party.members[0],
        target_dir=Direction.NORTH,
        party=cleric_party,
        world_map=state,
    )

    assert res.success
    assert cleric_party.gold > initial_gold
    assert cleric_party.members[0].hp == initial_hp
    assert dmap.get_tile(2, 2, 0) == DungeonTile.NOTHING


# --- Free combat spell limits (unchanged rule, re-verified) ---

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

    res1 = cast_spell(
        spell=Spell.PONTORI,
        caster=caster1,
        arena=arena,
        party=cleric_party,
    )
    assert res1.success

    res2 = cast_spell(
        spell=Spell.PONTORI,
        caster=caster1,
        arena=arena,
        party=cleric_party,
    )
    assert not res2.success
    assert "Can't!" in res2.message

    res3 = cast_spell(
        spell=Spell.PONTORI,
        caster=caster2,
        arena=arena,
        party=cleric_party,
    )
    assert res3.success

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


# --- Dungeon spells at full parity (SpellUtil.java:511-608) ---

def _dungeon(party, z=0, tile=DungeonTile.NOTHING):
    dmap = DungeonMap(id=99, name="TestDungeon", width=16, height=16, levels=8)
    dmap.tiles = [[[tile for _ in range(16)] for _ in range(16)] for _ in range(8)]
    return DungeonState(dmap, start_x=8, start_y=8, start_z=z, party=party)


def test_rec_su_climbs_and_relocates(cleric_party):
    state = _dungeon(cleric_party, z=2)
    res = cast_spell(
        spell=Spell.REC_SU,
        caster=cleric_party.members[0],
        party=cleric_party,
        world_map=state,
    )
    assert res.success
    assert state.z == 1
    assert cleric_party.dungeon_level == 1
    # Relocation lands on a valid spot of the new level
    assert 0 <= state.x < 16 and 0 <= state.y < 16


def test_sur_acron_climbs_out_at_level_zero(cleric_party):
    """spellYup at level 0 exits to the overworld (SpellUtil.java:514-519)."""
    state = _dungeon(cleric_party, z=0)
    res = cast_spell(
        spell=Spell.REC_SU,
        caster=cleric_party.members[0],
        party=cleric_party,
        world_map=state,
    )
    assert res.success
    assert res.exit_dungeon is True
    assert state.z == 0


def test_dor_acron_descends(cleric_party):
    state = _dungeon(cleric_party, z=1)
    res = cast_spell(
        spell=Spell.REC_DU,
        caster=cleric_party.members[0],
        party=cleric_party,
        world_map=state,
    )
    assert res.success
    assert state.z == 2
    assert cleric_party.dungeon_level == 2


def test_dor_acron_clamps_at_bottom_level(cleric_party):
    """spellZdown clamps at DUNGEON_LVLS and skips relocation there
    (SpellUtil.java:550-556)."""
    state = _dungeon(cleric_party, z=7)
    res = cast_spell(
        spell=Spell.REC_DU,
        caster=cleric_party.members[0],
        party=cleric_party,
        world_map=state,
    )
    assert res.success
    assert state.z == 8
    assert cleric_party.dungeon_level == 8
    assert (state.x, state.y) == (8, 8)  # no relocation off the deep end


def test_lib_rec_teleports_within_level(cleric_party):
    state = _dungeon(cleric_party, z=3)
    res = cast_spell(
        spell=Spell.LIB_REC,
        caster=cleric_party.members[0],
        party=cleric_party,
        world_map=state,
    )
    assert res.success
    assert state.z == 3
    assert cleric_party.dungeon_level == 3
    # Land is anywhere valid in the 16x16 level (all NOTHING here)
    assert 0 <= state.x < 16 and 0 <= state.y < 16


def test_sequitu_exits_with_label_log(cleric_party):
    """spellXit logs "Leaving " + label and transitions the screen (501-509)."""
    party = Party([PartyMember(Character("C", "F", Race.BOBIT, Profession.CLERIC, mp=60))])
    state = _dungeon(party, z=4)
    state.dmap.name = "Doom"
    res = cast_spell(
        spell=Spell.SEQUITU,
        caster=party.members[0],
        party=party,
        world_map=state,
    )
    assert res.success
    assert res.exit_dungeon is True
    assert "Leaving" in res.message
    assert "Doom" in res.message
