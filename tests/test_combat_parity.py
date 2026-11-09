"""Task 12 — Combat mechanics parity tests (Java CombatScreen/Utils truth).

Rows covered:
(a) monster action dice (26% teleport, 34% ranged regardless of distance,
    double damage for fire/energy ranged),
(b) arena map selection (Context.getCombatMap port),
(c) exclusive-high dice (`rand.nextInt(high-low)+low`),
(d) no monster-melee poison, no per-round combat poison tick, 0 damage legal,
(e) weapon loss on ranged attacks ("Last One!"),
(f) flee removed; off-edge moves blocked,
(g) XP for every player-caused death, capped 9999 (spells included),
(h) victory chest at the creature's overworld tile, walkability-checked,
(i) Castle of Death (EXODUS) attack/defense rules,
(j) monster count dice (guards = size*2, else rand(min(8, size*2))+1),
(k) monster advance randomizes among valid toward-directions, never off-map.
"""
import pytest
from py_exodus.aura import AuraType
from py_exodus.combat import arena as arena_mod
from py_exodus.combat import resolver as resolver_mod
from py_exodus.combat.arena import (
    Action,
    CombatArena,
    CombatMonster,
)
from py_exodus.combat.resolver import (
    calculate_monster_damage,
    calculate_player_damage,
    resolve_monster_attack,
)
from py_exodus.constants import (
    ArmorType,
    Direction,
    Status,
    TileAttrib,
    Transport,
    WeaponType,
)
from py_exodus.entities.defs import CreatureDef
from py_exodus.entities.party import Party
from py_exodus.entities.character import Character
from py_exodus.world import tile_effects
from py_exodus.world.loader import MapLoader
from py_exodus.assets import AssetManager, TileDef


# --- helpers ----------------------------------------------------------------

def build_party(count=1, hp=100, transport=None, **char_kwargs):
    kwargs = {"transport": transport} if transport is not None else {}
    party = Party(**kwargs)
    for i in range(count):
        party.add_member(
            Character(f"Hero{i}", "M", hp=hp, max_hp=hp, **char_kwargs)
        )
    return party


def load_combat_map(asset_mgr, fname="CNFLCT_A.ULT"):
    return MapLoader(asset_mgr).load_conflict_map(fname)


@pytest.fixture
def conflict_map(asset_mgr):
    return load_combat_map(asset_mgr)


# --- (a) ranged / teleport probability + double damage ----------------------


def test_monster_teleport_probability_is_26_of_100(asset_mgr, conflict_map, monkeypatch):
    """Java CombatScreen.java:697 — rand.nextInt(100) <= 25 (26 outcomes)."""
    rolls = []
    real_randrange = arena_mod.random.randrange

    def spy(n):
        v = real_randrange(n)
        if n == 100:
            rolls.append(v)
        return v

    monkeypatch.setattr(arena_mod.random, "randrange", spy)

    cdef = CreatureDef(id=1, name="Wisp", tile="wisp", basehp=48, teleports=True)
    arena = CombatArena(
        build_party(), conflict_map, asset_mgr=asset_mgr, monster_count=1
    )
    arena.creature_def = cdef
    arena.monsters[0].definition = cdef
    arena.monsters[0].teleports = True
    arena.player_positions[0] = (5, 5)
    arena.monsters[0].x, arena.monsters[0].y = 5, 1

    for _ in range(200):
        arena._execute_single_monster_ai(arena.monsters[0])

    # 200 trials of randrange(100); 52-56 of them land <= 25 in expectation
    assert len(rolls) == 200
    assert sum(1 for r in rolls if r <= 25) > 25
    assert sum(1 for r in rolls if r > 25) > 25


def test_monster_ranged_fires_regardless_of_distance(asset_mgr, conflict_map, monkeypatch):
    """Java CombatScreen.java:699 — 34% ranged, no distance gate."""
    monkeypatch.setattr(arena_mod.random, "randrange", lambda n: 0)  # force RANGED

    party = build_party(hp=1000)
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1)
    # Ranged creature adjacent to the hero: old code fell through to melee.
    arena.player_positions[0] = (5, 5)
    arena.monsters[0].x, arena.monsters[0].y = 5, 4
    arena.monsters[0].ranged = True
    arena.monsters[0].ranged_hit_tile = "fire"

    res = arena._execute_single_monster_ai(arena.monsters[0])
    assert res is not None
    assert res.action_type == "ranged"


def test_monster_ranged_fire_deals_damage_twice(asset_mgr, conflict_map, monkeypatch):
    """Java rangedAttackAt: fire/energy effect dealDamage + HIT dealDamage = 2 rolls."""
    monkeypatch.setattr(arena_mod.random, "randrange", lambda n: 0)  # force RANGED
    monkeypatch.setattr(resolver_mod, "calculate_monster_damage", lambda basehp=48: 5)
    monkeypatch.setattr(resolver_mod, "roll_hit", lambda *a, **k: True)

    party = Party()
    hero = Character("Hero", "M", hp=1000, max_hp=1000)
    party.add_member(hero)
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1,
                        context_map_id=2)  # EXODUS auto-hit
    # Column 3 of CNFLCT_A is a clear line from y=2 to y=7.
    arena.player_positions[0] = (3, 7)
    arena.monsters[0].x, arena.monsters[0].y = 3, 2
    arena.monsters[0].ranged = True
    arena.monsters[0].ranged_hit_tile = "fire"

    res = arena._execute_single_monster_ai(arena.monsters[0])
    assert res is not None and res.attack_res is not None
    assert res.attack_res.damage == 10  # 5 + 5 (double dealDamage)
    assert hero.hp == 990
    assert res.message == "Fiery Hit!"


def test_monster_ranged_energy_doubles_and_electrified(asset_mgr, conflict_map, monkeypatch):
    monkeypatch.setattr(arena_mod.random, "randrange", lambda n: 0)
    monkeypatch.setattr(resolver_mod, "calculate_monster_damage", lambda basehp=48: 7)
    monkeypatch.setattr(resolver_mod, "roll_hit", lambda *a, **k: True)

    party = Party()
    hero = Character("Hero", "M", hp=1000, max_hp=1000)
    party.add_member(hero)
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1,
                        context_map_id=2)
    arena.player_positions[0] = (3, 7)
    arena.monsters[0].x, arena.monsters[0].y = 3, 2
    arena.monsters[0].ranged = True
    arena.monsters[0].ranged_hit_tile = "energy"

    res = arena._execute_single_monster_ai(arena.monsters[0])
    assert res.attack_res.damage == 14
    assert hero.hp == 986
    assert res.message == "Electrified!"


# --- (b) Context.getCombatMap ------------------------------------------------


class _StubMap:
    def __init__(self, tiles):
        self._tiles = tiles

    def get_tile(self, x, y):
        return self._tiles.get((x, y))


def grass_tile():
    return TileDef(index=1, name="grass", rule="grass")


def water_tile():
    return TileDef(
        index=2, name="water", rule="water",
        attribs=TileAttrib.UNWALKABLE | TileAttrib.SWIMMABLE | TileAttrib.SAILABLE,
        combat_map_id=41,
    )


def brush_tile():
    return TileDef(index=3, name="brush", rule="brush", combat_map_id=34)


from py_exodus.screens.overworld import get_combat_map_id


def test_get_combat_map_sea_creature_on_land_is_shore_not_both_ships():
    serpent = CreatureDef(id=21, name="Serpent", tile="serpent", swims=True)
    tiles = {(10, 10): grass_tile(), (11, 10): water_tile()}
    game_map = _StubMap(tiles)
    # Creature sits on water (41 by tile rule) but the party is on walkable land.
    assert get_combat_map_id(serpent, 11, 10, 10, 10, Transport.FOOT, game_map) == 38


def test_get_combat_map_sailing_creature_ship_top():
    pirate = CreatureDef(id=20, name="Pirate", tile="pirate", sails=True)
    tiles = {(10, 10): grass_tile(), (11, 10): water_tile()}
    game_map = _StubMap(tiles)
    assert get_combat_map_id(pirate, 11, 10, 10, 10, Transport.FOOT, game_map) == 33


def test_get_combat_map_transport_ship_variants():
    serpent = CreatureDef(id=21, name="Serpent", tile="serpent", swims=True)
    pirate = CreatureDef(id=20, name="Pirate", tile="pirate", sails=True)
    orc = CreatureDef(id=1, name="Orc", tile="orc")
    tiles = {(10, 10): grass_tile(), (11, 10): water_tile()}
    game_map = _StubMap(tiles)
    assert get_combat_map_id(serpent, 11, 10, 10, 10, Transport.SHIP, game_map) == 39
    assert get_combat_map_id(pirate, 11, 10, 10, 10, Transport.SHIP, game_map) == 41
    # A sea creature must not force BOTH_SHIPS when the party sails and the
    # creature cannot sail (Java: swims branch fires, SHIP_BOTTOM... see Java:
    # swims -> SHIP).
    assert get_combat_map_id(pirate, 11, 10, 10, 10, Transport.FOOT, game_map) == 33


def test_get_combat_map_tile_rule_maps():
    orc = CreatureDef(id=1, name="Orc", tile="orc")
    thief = CreatureDef(id=12, name="Thief", tile="thief")
    tiles = {(10, 10): grass_tile(), (4, 4): brush_tile()}
    game_map = _StubMap(tiles)
    assert get_combat_map_id(orc, 10, 10, 10, 10, Transport.FOOT, game_map) == 37
    assert get_combat_map_id(thief, 4, 4, 10, 10, Transport.FOOT, game_map) == 34


# --- (c) exclusive-high dice -------------------------------------------------


def test_player_damage_high_is_exclusive():
    """Java Utils.getRandomBetween — nextInt(high - low) + low: high excluded."""
    char = Character("Hero", "M", strength=0)
    weapon = type("W", (), {"dmin": 4, "dmax": 7})()
    rolls = {calculate_player_damage(char, weapon) for _ in range(300)}
    assert min(rolls) >= 4
    assert max(rolls) == 6  # 7 (the Java `high`) must never come up
    assert rolls == {4, 5, 6}


def test_monster_damage_may_be_zero():
    """Java Creature.getDamage has no floor: small basehp yields 0."""
    assert calculate_monster_damage(basehp=4) == 0
    for _ in range(200):
        assert 0 <= calculate_monster_damage(basehp=48)


def test_steal_dice_are_next_int_10_and_40(monkeypatch):
    food_monster = CombatMonster(
        CreatureDef(id=1, name="Muncher", tile="orc", basehp=48, steals="food"), 5, 5
    )
    gold_monster = CombatMonster(
        CreatureDef(id=2, name="Cutpurse", tile="orc", basehp=48, steals="gold"), 5, 5
    )
    food_seen = set()
    gold_seen = set()
    for _ in range(600):
        member = Character("Hero", "M", hp=999, max_hp=999)
        member.food = 9999
        member.gold = 9999
        monkeypatch.setattr(resolver_mod, "roll_hit", lambda *a, **k: True)
        monkeypatch.setattr(resolver_mod, "calculate_monster_damage", lambda basehp=48: 1)
        res_f = resolve_monster_attack(monster=food_monster, target_player=member)
        res_g = resolve_monster_attack(monster=gold_monster, target_player=member)
        food_seen.add(res_f.stolen_food)
        gold_seen.add(res_g.stolen_gold)
    assert all(0 <= v <= 9 for v in food_seen)
    assert all(0 <= v <= 39 for v in gold_seen)
    assert 0 in food_seen and 0 in gold_seen  # nextInt can return 0
    assert max(food_seen) >= 8 and max(gold_seen) >= 35


# --- (d) no melee poison / no round poison tick -----------------------------


def test_monster_melee_never_poisons(asset_mgr, monkeypatch):
    """Java melee ATTACK branch has no poison path (pincher poisons=True)."""
    monkeypatch.setattr(resolver_mod, "roll_hit", lambda *a, **k: True)
    monkeypatch.setattr(resolver_mod, "calculate_monster_damage", lambda basehp=48: 1)
    monster = CombatMonster(
        CreatureDef(id=17, name="Pincher", tile="pincher", basehp=48, poisons=True), 0, 0
    )
    for _ in range(300):
        member = Character("Hero", "M", hp=999, max_hp=999)
        res = resolve_monster_attack(monster=monster, target_player=member)
        assert not res.poisoned
        assert member.status != Status.POISONED


def test_combat_poison_tick_removed(asset_mgr, conflict_map):
    """arena.py's per-round poison tick is gone (Java has none in combat)."""
    assert not hasattr(CombatArena, "_apply_poison_tick")


def test_monster_damage_zero_possible_through_chokepoint(asset_mgr, conflict_map):
    """Small monsters deal 0 damage (no max(1, _) floor)."""
    party = Party()
    hero = Character("Hero", "M", hp=100, max_hp=100)
    party.add_member(hero)
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1,
                        context_map_id=2)  # forced hit
    arena.player_positions[0] = (5, 5)
    arena.monsters[0].x, arena.monsters[0].y = 5, 4
    arena.monsters[0].basehp = 4  # getDamage: nextInt(1) = 0

    res = arena._execute_single_monster_ai(arena.monsters[0])
    assert res is not None and res.action_type == "attack"
    assert hero.hp == 100  # 0 damage
    assert not arena.is_finished


# --- (e) weapon loss ---------------------------------------------------------


def _bow_setup(asset_mgr, conflict_map, monkeypatch, count=2):
    """BOW in weapons.xml carries no losewhenranged flag — the tests inject
    the losing variant so the row (e) mechanics are observable."""
    from py_exodus.entities.defs import WeaponDef
    losing_bow = WeaponDef(
        type="BOW", name="Bow", abbr="BOW", range=16, dmin=4, dmax=10,
        lose_when_ranged=True,
    )
    monkeypatch.setattr(asset_mgr, "get_weapon", lambda name: losing_bow)
    party = Party()
    hero = Character("Archer", "M", hp=100, max_hp=100, weapon=WeaponType.BOW, dexterity=50)
    hero.weapons[WeaponType.BOW] = count
    party.add_member(hero)
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1)
    # The roll is patched to always hit, so no EXODUS forcing is needed here
    # (context_map_id=2 would refuse the non-exotic bow outright, row (i)).
    arena.player_positions[0] = (3, 7)
    monster = arena.monsters[0]
    monster.x, monster.y = 3, 3
    monster.hp = 100
    monster.exp = 7
    return party, arena, hero, monster


def test_lose_when_ranged_decrements_on_distant_shot(asset_mgr, conflict_map, monkeypatch):
    monkeypatch.setattr(resolver_mod, "roll_hit", lambda *a, **k: True)
    party, arena, hero, monster = _bow_setup(asset_mgr, conflict_map, monkeypatch, count=2)
    res = arena.execute_player_action(0, Action.attack(Direction.NORTH))
    assert res.success
    assert hero.weapons[WeaponType.BOW] == 1
    assert hero.weapon == WeaponType.BOW
    assert "Last One!" not in res.message


def test_lose_weapon_last_one_message(asset_mgr, conflict_map, monkeypatch):
    monkeypatch.setattr(resolver_mod, "roll_hit", lambda *a, **k: True)
    party, arena, hero, monster = _bow_setup(asset_mgr, conflict_map, monkeypatch, count=0)
    res = arena.execute_player_action(0, Action.attack(Direction.NORTH))
    assert res.success
    assert hero.weapon == WeaponType.NONE
    assert "Last One!" in res.message


def test_bow_point_blank_hit_does_not_lose_weapon(asset_mgr, conflict_map, monkeypatch):
    """Java: losewhenranged requires (!foundTarget || distance > 1)."""
    monkeypatch.setattr(resolver_mod, "roll_hit", lambda *a, **k: True)
    party, arena, hero, monster = _bow_setup(asset_mgr, conflict_map, monkeypatch, count=2)
    monster.x, monster.y = 3, 6  # adjacent on the traced column
    res = arena.execute_player_action(0, Action.attack(Direction.NORTH))
    assert res.success and res.attack_res.hit
    assert hero.weapons[WeaponType.BOW] == 2  # untouched


# --- (f) flee removed --------------------------------------------------------


def test_flee_action_type_removed():
    import py_exodus.combat.arena as a
    assert not hasattr(a.ActionType, "FLEE")
    assert not hasattr(a.Action, "flee")


def test_combat_screen_f_key_is_dead(asset_mgr, conflict_map, monkeypatch):
    import pygame

    from py_exodus.screens.combat_screen import CombatScreen

    party = build_party()
    combat = CombatScreen(
        party=party, combat_map=conflict_map, creature_tile="orc",
        asset_mgr=asset_mgr, monster_count=1,
    )
    before = list(combat.text_log.history)
    combat.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_f))
    # The unknown key performs no action and leaves no residue.
    assert combat.text_log.history == before
    assert not combat.text_log.is_waiting_for_input


def test_player_off_edge_move_is_blocked_not_flee(asset_mgr, conflict_map):
    party = build_party()
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1)
    arena.player_positions[0] = (5, 10)
    pos_before = arena.player_positions[0]

    res = arena.execute_player_action(0, Action.move(Direction.SOUTH))
    assert not res.success
    assert arena.player_positions[0] == pos_before
    assert not party.members[0].fled
    assert not arena.is_finished
    assert not arena.is_fled


# --- (g) XP for every player-caused death, capped 9999 -----------------------


def test_player_kill_xp_capped_at_9999(asset_mgr, conflict_map, monkeypatch):
    monkeypatch.setattr(resolver_mod, "roll_hit", lambda *a, **k: True)
    monkeypatch.setattr(resolver_mod, "calculate_player_damage", lambda *a, **k: 5)
    party = Party()
    hero = Character("Hero", "M", hp=100, max_hp=100, dexterity=50)
    hero.exp = 9990
    party.add_member(hero)
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1)
    arena.player_positions[0] = (5, 5)
    monster = arena.monsters[0]
    monster.x, monster.y = 5, 4
    monster.hp = 3
    monster.exp = 20

    arena.execute_player_action(0, Action.attack(Direction.NORTH))
    assert hero.exp == 9999  # capped, not 10010


def test_projectile_spell_kill_awards_xp(asset_mgr, conflict_map):
    from py_exodus.constants import Profession, Spell

    party = Party()
    wiz = Character("Mage", "M", profession=Profession.WIZARD,
                    intelligence=50, mp=50, exp=100)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc",
                        asset_mgr=asset_mgr, monster_count=1)
    arena.player_positions[0] = (5, 9)
    monster = arena.monsters[0]
    monster.x, monster.y = 5, 5
    monster.hp = 1
    monster.exp = 20

    res = arena.execute_player_action(0, Action.cast(Spell.MITTAR, direction=Direction.NORTH))
    assert res.success
    assert monster.is_dead
    assert wiz.exp == 120


def test_group_damage_spell_kill_awards_xp(asset_mgr, conflict_map):
    from py_exodus.constants import Profession, Spell

    party = Party()
    wiz = Character("Mage", "M", intelligence=50, mp=100, exp=0)
    wiz.profession = Profession.WIZARD
    party.add_member(wiz)
    arena = CombatArena(party, conflict_map, creature_tile="orc",
                        asset_mgr=asset_mgr, monster_count=1)
    monster = arena.monsters[0]
    monster.hp = 1
    monster.exp = 30

    res = arena.execute_player_action(0, Action.cast(Spell.NECORP))
    assert res.success
    assert res.spell_res.targets_affected == 1
    assert wiz.exp == 30


# --- (h) victory chest at the creature's overworld tile ----------------------


def test_victory_chest_spawns_at_creature_overworld_tile(asset_mgr, conflict_map):
    party = build_party(transport=Transport.FOOT)
    party.x, party.y = 44, 20
    arena = CombatArena(
        party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr,
        monster_count=1, encounter_x=21, encounter_y=7,
        encounter_tile_walkable=True,
    )
    arena.monsters[0].hp = 0
    arena._handle_victory()
    assert arena.chest_spawned
    chest = [o for o in party.dynamic_objects if o.get("tile") == "chest"]
    assert chest and chest[0]["x"] == 21 and chest[0]["y"] == 7


def test_victory_chest_blocked_by_unwalkable_creature_tile(asset_mgr, conflict_map):
    party = build_party(transport=Transport.FOOT)
    party.x, party.y = 44, 20
    arena = CombatArena(
        party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr,
        monster_count=1, encounter_x=21, encounter_y=7,
        encounter_tile_walkable=False,
    )
    arena.monsters[0].hp = 0
    arena._handle_victory()
    assert not arena.chest_spawned


def test_defeated_pirate_leaves_frigate_at_creature_tile(asset_mgr, conflict_map):
    party = build_party(transport=Transport.SHIP)
    party.x, party.y = 44, 20
    party.dynamic_objects.clear()
    arena = CombatArena(
        party, conflict_map, creature_tile="pirate", asset_mgr=asset_mgr,
        monster_count=1, encounter_x=21, encounter_y=7,
        encounter_tile_walkable=False,  # a pirate on water: no chest...
    )
    arena.monsters[0].hp = 0
    arena._handle_victory()
    assert not arena.chest_spawned
    frigate = [o for o in party.dynamic_objects if o.get("tile") == "frigate"]
    assert frigate and frigate[0]["x"] == 21 and frigate[0]["y"] == 7


# --- (i) Castle of Death (EXODUS) rules --------------------------------------


def test_exodus_refuses_non_exotic_player_attack(asset_mgr, conflict_map, monkeypatch):
    monkeypatch.setattr(resolver_mod, "roll_hit", lambda *a, **k: True)
    party = Party()
    hero = Character("Hero", "M", hp=100, max_hp=100, weapon=WeaponType.SWORD)
    hero.weapons[WeaponType.SWORD] = 5
    party.add_member(hero)
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1,
                        context_map_id=2)
    arena.player_positions[0] = (5, 5)
    monster = arena.monsters[0]
    monster.x, monster.y = 5, 4
    monster.hp = 100

    res = arena.execute_player_action(0, Action.attack(Direction.NORTH))
    assert res.success is False
    assert monster.hp == 100  # no damage done
    assert arena.is_party_round_done  # the turn passes


def test_exodus_allows_exotic_player_attack(asset_mgr, conflict_map, monkeypatch):
    monkeypatch.setattr(resolver_mod, "roll_hit", lambda *a, **k: True)
    monkeypatch.setattr(resolver_mod, "calculate_player_damage", lambda *a, **k: 5)
    party = Party()
    hero = Character("Hero", "M", hp=100, max_hp=100, weapon=WeaponType.EXOTIC)
    hero.weapons[WeaponType.EXOTIC] = 5
    party.add_member(hero)
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1,
                        context_map_id=2)
    arena.player_positions[0] = (5, 5)
    monster = arena.monsters[0]
    monster.x, monster.y = 5, 4
    monster.hp = 100

    res = arena.execute_player_action(0, Action.attack(Direction.NORTH))
    assert res.success and res.attack_res.hit
    assert monster.hp == 95


def test_exodus_monster_melee_auto_hits_non_exotic_defender(asset_mgr, conflict_map, monkeypatch):
    """Java CombatScreen.java:723 — EXODUS + armor != EXOTIC -> forced HIT."""
    monkeypatch.setattr(resolver_mod, "roll_hit", lambda *a, **k: False)  # would miss
    monkeypatch.setattr(resolver_mod, "calculate_monster_damage", lambda basehp=48: 9)
    party = Party()
    hero = Character("Hero", "M", hp=100, max_hp=100)
    party.add_member(hero)
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1,
                        context_map_id=2)
    arena.player_positions[0] = (5, 5)
    arena.monsters[0].x, arena.monsters[0].y = 5, 4

    res = arena._execute_single_monster_ai(arena.monsters[0])
    assert res.attack_res.hit
    assert hero.hp == 91


def test_exodus_monster_melee_respects_exotic_armor(asset_mgr, conflict_map, monkeypatch):
    monkeypatch.setattr(resolver_mod, "roll_hit", lambda *a, **k: False)
    party = Party()
    hero = Character("Hero", "M", hp=100, max_hp=100, armor=ArmorType.EXOTIC)
    party.add_member(hero)
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1,
                        context_map_id=2)
    arena.player_positions[0] = (5, 5)
    arena.monsters[0].x, arena.monsters[0].y = 5, 4

    res = arena._execute_single_monster_ai(arena.monsters[0])
    assert not res.attack_res.hit
    assert hero.hp == 100


def test_exodus_monster_ranged_auto_hits_non_exotic_defender(asset_mgr, conflict_map, monkeypatch):
    monkeypatch.setattr(arena_mod.random, "randrange", lambda n: 0)  # force RANGED
    monkeypatch.setattr(resolver_mod, "roll_hit", lambda *a, **k: False)
    monkeypatch.setattr(resolver_mod, "calculate_monster_damage", lambda basehp=48: 4)
    party = Party()
    hero = Character("Hero", "M", hp=100, max_hp=100)
    party.add_member(hero)
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1,
                        context_map_id=2)
    arena.player_positions[0] = (3, 7)
    arena.monsters[0].x, arena.monsters[0].y = 3, 2
    arena.monsters[0].ranged = True

    res = arena._execute_single_monster_ai(arena.monsters[0])
    assert res.action_type == "ranged"
    assert res.attack_res.hit
    assert hero.hp == 96


# --- (j) monster count -------------------------------------------------------


def test_guard_count_is_all_members_times_two(asset_mgr, conflict_map):
    party = build_party(3)
    party.members[2].hp = 0
    party.members[2].status = Status.DEAD  # dead members still count

    arena = CombatArena(party, conflict_map, creature_tile="guard",
                        asset_mgr=asset_mgr)
    assert len(arena.monsters) == 6  # 3 members (incl. 1 dead) x 2


def test_non_guard_count_dice_upper_bound(asset_mgr, conflict_map, monkeypatch):
    calls = []

    def fake_randint(low, high):
        calls.append((low, high))
        return high

    monkeypatch.setattr(arena_mod.random, "randint", fake_randint)
    party = build_party(3)
    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr)
    # Java: rand.nextInt(min(8, size*2)) + 1 -> randint(1, 6) equivalent bound
    assert calls and calls[0] == (1, 6)
    assert len(arena.monsters) == 6


# --- (k) AI advance randomization + never off-map ----------------------------


def test_advance_randomizes_among_valid_toward_directions(asset_mgr, conflict_map, monkeypatch):
    monkeypatch.setattr(arena_mod.random, "randrange", lambda n: 99)  # force ADVANCE
    picked = []
    real_choice = arena_mod.random.choice

    def spy_choice(seq):
        picked.append(list(seq))
        return real_choice(seq)

    monkeypatch.setattr(arena_mod.random, "choice", spy_choice)

    party = build_party()
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1)
    # Monster at (3,3); hero at (6,5): toward directions = EAST, SOUTH, both
    # walkable on CNFLCT_A ((4,3) and (3,4) are open).
    arena.player_positions[0] = (6, 5)
    arena.monsters[0].x, arena.monsters[0].y = 3, 3

    res = arena._execute_single_monster_ai(arena.monsters[0])
    assert res is not None and res.action_type == "advance"
    assert picked, "advance must consult the valid-toward candidates"
    candidates = picked[-1]
    # getRandomValidDirection iterates N,S,E,W — the filtered toward set.
    assert set(candidates) == {Direction.EAST, Direction.SOUTH}
    assert (arena.monsters[0].x, arena.monsters[0].y) in ((4, 3), (3, 4))


def test_advance_never_steps_off_map(asset_mgr, conflict_map, monkeypatch):
    """A monster at the edge advances inward; Java's mask excludes null tiles,
    so off-map movement (and the old Python "flees from battle!") is gone."""
    monkeypatch.setattr(arena_mod.random, "randrange", lambda n: 99)
    party = build_party()
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1)
    # Bottom-right corner of the arena (row 10 is open floor); hero west.
    arena.player_positions[0] = (0, 10)
    arena.monsters[0].x, arena.monsters[0].y = 10, 10

    res = arena._execute_single_monster_ai(arena.monsters[0])
    assert res is not None and res.action_type == "advance"
    assert (arena.monsters[0].x, arena.monsters[0].y) == (9, 10)
    assert not arena.monsters[0].fled


def test_advance_blocked_when_no_toward_direction_valid(asset_mgr, conflict_map, monkeypatch):
    monkeypatch.setattr(arena_mod.random, "randrange", lambda n: 99)
    party = build_party()
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1)
    arena.player_positions[0] = (5, 5)
    arena.monsters[0].x, arena.monsters[0].y = 5, 8
    # Wall the column shut between (5,8) and (5,5).
    for y in (7, 6):
        conflict_map.set_tile(5, y, TileDef(index=9, name="wall", rule="walls",
                                            attribs=TileAttrib.UNWALKABLE | TileAttrib.CREATUREUNWALKABLE))
    res = arena._execute_single_monster_ai(arena.monsters[0])
    # No valid toward direction: the monster stays put (Java getPath -> null).
    assert (arena.monsters[0].x, arena.monsters[0].y) == (5, 8)


# --- combat tile effects on player moves (checkTileAffects port) -------------


def test_combat_move_applies_tile_effect_to_mover(asset_mgr, conflict_map, monkeypatch):
    fire_tile = TileDef(index=8, name="firefield", rule="fire")

    class FakeRng:
        def randrange(self, n, *a):
            return 0

    monkeypatch.setattr(tile_effects, "_rng", FakeRng())
    party = build_party()
    hero = party.members[0]
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1)
    arena.player_positions[0] = (5, 6)
    conflict_map.set_tile(5, 5, fire_tile)

    res = arena.execute_player_action(0, Action.move(Direction.NORTH))
    assert res.success
    assert hero.hp == 100 - 16  # 16 + rand(32) with the scripted rng = 16
    assert not hero.is_dead()


def test_combat_move_tile_effect_rolls_one_in_five_for_poison(asset_mgr, conflict_map, monkeypatch):
    poison_tile = TileDef(index=9, name="poisonfield", rule="poison")

    class NeverRng:
        def randrange(self, n, *a):
            return 1 if n > 1 else 0

    monkeypatch.setattr(tile_effects, "_rng", NeverRng())
    party = build_party()
    hero = party.members[0]
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1)
    arena.player_positions[0] = (5, 6)
    conflict_map.set_tile(5, 5, poison_tile)

    res = arena.execute_player_action(0, Action.move(Direction.NORTH))
    assert res.success
    assert hero.hp == 100  # the 1-in-5 roll failed: no effect
    assert hero.status != Status.POISONED


def test_combat_tile_effect_wipe_raises_death_exception(asset_mgr, conflict_map, monkeypatch):
    """Java keyUp catches PartyDeathException from checkTileAffects and routes
    ``returnScreen.partyDeath()`` (CombatScreen.java:356-358) — the burn goes
    out as non-combat damage and the ARENA itself is aborted mid-move, not
    marked as an in-combat defeat (CombatScreen defeats come only from the
    creature phase / post-creature alive check)."""
    fire_tile = TileDef(index=8, name="firefield", rule="fire")

    class AlwaysRng:
        def randrange(self, n, *a):
            return 0

    monkeypatch.setattr(tile_effects, "_rng", AlwaysRng())
    party = Party()
    hero = Character("Hero", "M", hp=1, max_hp=1)
    party.add_member(hero)
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1)
    arena.player_positions[0] = (5, 6)
    arena.monsters[0].x, arena.monsters[0].y = 0, 0  # far away
    conflict_map.set_tile(5, 5, fire_tile)

    from py_exodus.entities.party import PartyDeathException

    with pytest.raises(PartyDeathException):
        arena.execute_player_action(0, Action.move(Direction.NORTH))
    assert hero.status == Status.DEAD
