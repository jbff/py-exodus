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


def test_variant_art_sits_at_lairware_tiles_64_to_79():
    assert VARIANT_TILE_INDEX["thief"] == (64, 65)
    assert VARIANT_TILE_INDEX["balron"] == (78, 79)


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
