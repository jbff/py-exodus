"""LairWare monster variants: Brigand, Goblin, Devil... (user request
2026-11-22: the original's three names per monster type)."""
import random

from py_exodus.world.monster_variants import (
    VARIANT_TILE_INDEX,
    roll_variant,
    variant_name,
)


def test_each_named_type_has_lairwares_two_variant_names():
    assert variant_name("thief", 1) == "Brigand"
    assert variant_name("thief", 2) == "Cutpurse"
    assert variant_name("orc", 1) == "Goblin"
    assert variant_name("orc", 2) == "Troll"
    assert variant_name("balron", 1) == "Orcus"
    assert variant_name("balron", 2) == "Devil"
    assert variant_name("pincher", 2, plural=True) == "Bradles"
    assert variant_name("thief", 0) is None  # plain: base name
    assert variant_name("fighter", 1) is None  # LW names Thief..Balron only


def test_variant_art_sits_at_lairware_sheet_cells_80_to_95():
    assert VARIANT_TILE_INDEX["thief"] == (80, 81)
    assert VARIANT_TILE_INDEX["balron"] == (94, 95)


def test_variant_roll_is_half_plain_then_even():
    rng = random.Random(1)
    rolls = [roll_variant(rng) for _ in range(4000)]
    assert 1700 < rolls.count(0) < 2300
    assert 800 < rolls.count(1) < 1200
    assert 800 < rolls.count(2) < 1200


def test_spawned_wanderer_carries_its_variant_into_combat(asset_mgr, monkeypatch):
    """A Cutpurse on the map fights as Cutpurses (LairWare gMonVarType)."""
    from py_exodus.combat.arena import CombatArena
    from py_exodus.entities.character import Character
    from py_exodus.entities.party import Party
    from tests.test_combat_parity import load_combat_map

    party = Party()
    party.add_member(Character("Hero", "M", hp=200, max_hp=200))
    cmap = load_combat_map(asset_mgr)
    arena = CombatArena(party, cmap, creature_tile="thief", asset_mgr=asset_mgr,
                        monster_count=2, creature_variant=2)
    assert {m.name for m in arena.monsters} == {"Cutpurse"}
    plain = CombatArena(party, cmap, creature_tile="thief", asset_mgr=asset_mgr,
                        monster_count=1)
    assert plain.monsters[0].name == "Thief"


def test_overworld_spawn_names_the_variant(asset_mgr, monkeypatch):
    from py_exodus.entities.character import Character
    from py_exodus.entities.party import Party
    from py_exodus.screens import overworld as ow_mod
    from py_exodus.screens.overworld import OverworldScreen

    party = Party()
    party.add_member(Character("Hero", "M", hp=200, max_hp=200))
    ow = OverworldScreen(party=party, asset_mgr=asset_mgr, random_encounters=False)
    ow.creatures = []
    monkeypatch.setattr(ow_mod, "roll_variant", lambda: 1)
    monkeypatch.setattr(ow, "_pick_creature_for_tile", lambda tile: "orc")
    monkeypatch.setattr(ow_mod.random, "randint", lambda a, b: 134 if b == 134 else (a + b) // 2)
    for _ in range(50):
        ow._spawn_wandering_creature()
        if ow.creatures:
            break
    orc = ow.creatures[0]
    assert orc["variant"] == 1 and orc["name"] == "Goblin"


def test_tiles_flag_loads_a_lairware_sheet_with_variant_art():
    """--tiles c64: every tile 0-63 comes from the C64 sheet, at our tile
    size; the variants get their own art; the default is LairWare Standard."""
    from pathlib import Path

    from py_exodus.assets import LAIRWARE_TILESETS, AssetManager

    plain = AssetManager(assets_dir=Path("assets"))
    plain.load_tiles()
    for name in LAIRWARE_TILESETS:
        am = AssetManager(assets_dir=Path("assets"), tileset=name)
        am.load_tiles()
        assert am.tiles["grass"][0].get_size() == plain.tiles["grass"][0].get_size()
        assert len(am.tiles["orc"]) == 2
        assert "goblin" in am.tiles and "devil" in am.tiles
    c64 = AssetManager(assets_dir=Path("assets"), tileset="c64")
    c64.load_tiles()
    assert c64.tiles["orc"][0].get_at((8, 8)) != plain.tiles["orc"][0].get_at((8, 8)) or \
        c64.tiles["water"][0].get_at((3, 3)) != plain.tiles["water"][0].get_at((3, 3))
    assert "goblin" in plain.tiles and plain.tileset is None


def test_unknown_tile_set_is_refused():
    import pytest

    from pathlib import Path

    from py_exodus.assets import AssetManager

    am = AssetManager(assets_dir=Path("assets"), tileset="atari")
    with pytest.raises(ValueError):
        am.load_tiles()


def test_lairware_sheet_does_not_animate_still_tiles():
    """User 2026-11-22: C64 town walls blinked with Exodus castle art. The
    cell beside a still tile is other art, not a second frame."""
    from pathlib import Path

    from py_exodus.assets import LAIRWARE_TILESETS, AssetManager

    plain = AssetManager(assets_dir=Path("assets"))
    plain.load_tiles()
    for sheet in LAIRWARE_TILESETS:  # c64 and ultima5 were both reported
        am = AssetManager(assets_dir=Path("assets"), tileset=sheet)
        am.load_tiles()
        for name, frames in plain.tiles.items():
            if name in am.tiles and len(frames) == 1:
                assert len(am.tiles[name]) == 1, (sheet, name)
        assert len(am.tiles["wall"]) == 1
