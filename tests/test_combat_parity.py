"""Task 12 — Combat mechanics parity tests (Java CombatScreen/Utils truth).

Rows covered:
(a) monster action dice (26% teleport, 34% ranged regardless of distance,
    double damage for fire/energy ranged),
(b) arena map selection (Context.getCombatMap port),
(c) exclusive-high dice (`rand.nextInt(high-low)+low`),
(d) monster-melee poison per GBC rule (2026-11-14 deviation), no per-round
    combat poison tick, 0 damage legal,
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
    monster_damage_bonus,
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


def test_monster_melee_poisons_per_gbc_rule(asset_mgr, monkeypatch):
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): poisoner melee hits roll
    1-in-4 poison (GBC battle3.c:267-277); Java's melee branch has no poison."""
    monkeypatch.setattr(resolver_mod, "roll_hit", lambda *a, **k: True)
    monkeypatch.setattr(resolver_mod, "calculate_monster_damage", lambda basehp=48: 1)
    monster = CombatMonster(
        CreatureDef(id=17, name="Pincher", tile="pincher", basehp=48, poisons=True), 0, 0
    )
    poisoned = 0
    for _ in range(200):
        member = Character("Hero", "M", hp=999, max_hp=999)
        res = resolve_monster_attack(monster=monster, target_player=member)
        assert res.poisoned == (member.status == Status.POISONED)
        poisoned += bool(res.poisoned)
    assert 25 <= poisoned <= 75  # 1-in-4 across 200 trials (expected 50)


def test_combat_poison_tick_removed(asset_mgr, conflict_map):
    """arena.py's per-round poison tick is gone (Java has none in combat)."""
    assert not hasattr(CombatArena, "_apply_poison_tick")


def test_monster_damage_zero_possible_through_chokepoint(asset_mgr, conflict_map):
    """Small monsters roll 0 base damage (no max(1, _) floor).

    USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): the GBC terrain bonus is
    added to the roll even when it lands 0, so on the Castle of Death context
    (EXODUS, tier +20) the member takes the bonus, not zero
    (GBC battle3.c:337-350)."""
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
    assert hero.hp == 100 - monster_damage_bonus(2)  # base roll 0 + terrain bonus
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


def test_necorp_weakens_without_killing_or_xp(asset_mgr, conflict_map):
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): NECORP sets living
    monsters' hp to 5 and kills nothing — no EXP is paid (GBC battle.c:1361-1373;
    LW UltimaSpellCombat.c:498-520)."""
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
    assert monster.hp == 5  # raised from 1 — the exact-set rule
    assert not monster.is_dead
    assert monster.weakened
    assert wiz.exp == 0


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


class _SfxRecorder:
    """Records play_sfx names; stand-in for AudioManager in screen tests."""

    def __init__(self):
        self.played = []

    def play_sfx(self, name, volume=None):
        self.played.append(name)
        return True

    def play_music(self, name, **kwargs):
        return True

    def stop_music(self, **kwargs):
        return True


def test_exodus_attack_refusal_plays_java_sfx(asset_mgr, conflict_map, pygame_setup):
    """Java SecondaryInputProcessor.java:345-347 — on EXODUS a non-exotic
    weapon attack is refused with Sound.NEGATIVE_EFFECT, not PC_ATTACK; a
    normal (non-EXODUS) attack still plays PC_ATTACK."""
    from py_exodus.screens.combat_screen import CombatScreen

    party = Party()
    hero = Character("Hero", "M", hp=100, max_hp=100, weapon=WeaponType.SWORD)
    hero.weapons[WeaponType.SWORD] = 5
    party.add_member(hero)

    recorder = _SfxRecorder()
    combat = CombatScreen(
        party=party, combat_map=conflict_map, creature_tile="orc",
        asset_mgr=asset_mgr, monster_count=1, context_map_id=2,
        audio=recorder,
    )
    combat._execute_action(Action.attack(Direction.NORTH))
    assert recorder.played == ["negative_effect"]

    # Control: the same attack off-EXODUS still plays PC_ATTACK.
    recorder.played.clear()
    normal_party = Party()
    normal_hero = Character("Hero", "M", hp=100, max_hp=100, weapon=WeaponType.SWORD)
    normal_hero.weapons[WeaponType.SWORD] = 5
    normal_party.add_member(normal_hero)
    normal_combat = CombatScreen(
        party=normal_party, combat_map=conflict_map, creature_tile="orc",
        asset_mgr=asset_mgr, monster_count=1, context_map_id=0,
        audio=recorder,
    )
    normal_combat._execute_action(Action.attack(Direction.NORTH))
    assert recorder.played == ["pc_attack"]


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
    # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): 9 rolled + EXODUS terrain
    # tier +20 (GBC battle3.c:337-350).
    assert hero.hp == 100 - (9 + monster_damage_bonus(2))


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


def test_guard_count_is_party_size_independent_eight(asset_mgr, conflict_map):
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): encounter size per
    funcs5.c:1573-1608 (Java party-size formula superseded) — guard battles
    spawn 8 regardless of party size (Java counted size*2 members, dead
    included; CombatScreen.java:193-202)."""
    party = build_party(3)
    party.members[2].hp = 0
    party.members[2].status = Status.DEAD  # dead members no longer affect the count

    arena = CombatArena(party, conflict_map, creature_tile="guard",
                        asset_mgr=asset_mgr)
    assert len(arena.monsters) == 8


def test_non_guard_count_dice_upper_bound(asset_mgr, conflict_map, monkeypatch):
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): encounter size per
    funcs5.c:1573-1608 (Java party-size formula superseded) — the non-guard
    count rolls randint(1, 8) with no party-size term (Java rolled
    nextInt(min(8, size*2)) + 1)."""
    calls = []

    def fake_randint(low, high):
        calls.append((low, high))
        return high

    monkeypatch.setattr(arena_mod.random, "randint", fake_randint)
    party = build_party(3)
    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr)
    assert calls and calls[0] == (1, 8)
    assert len(arena.monsters) == 8


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
    assert hero.hp == 100 - 50  # flat 50 (GBC funcs5.c:1287-1310)
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


# --- fix round 1 (row k): occupancy blocking --------------------------------


def test_monsters_converging_cannot_share_a_tile(asset_mgr, monkeypatch):
    """Java hasBlockingCreatureAt (BaseMap.java:762-769) blocks any creature
    tile in the movement mask — two converging monsters never stack."""
    monkeypatch.setattr(arena_mod.random, "randrange", lambda n: 99)  # force ADVANCE
    party = build_party()
    arena = CombatArena(
        party, load_combat_map(asset_mgr, "CNFLCT_G.ULT"),
        asset_mgr=asset_mgr, monster_count=2,
    )
    arena.player_positions[0] = (5, 5)
    arena.monsters[0].x, arena.monsters[0].y = 3, 5
    arena.monsters[1].x, arena.monsters[1].y = 7, 5
    for m in arena.monsters:
        m.basehp = 4  # 0 damage: the hero stays alive on the same tile

    for _ in range(4):
        for monster in list(arena.monsters):
            arena._execute_single_monster_ai(monster)
        tiles = [(m.x, m.y) for m in arena.monsters]
        assert len(set(tiles)) == len(tiles)


def test_monster_cannot_step_onto_dead_member_tile(asset_mgr, monkeypatch):
    """A dead party member still occupies their start tile (CombatScreen.java:
    125-147 combatCr assignment, hasBlockingCombatPlayerAt skips only fled) and
    blocks the advance like any other occupied tile."""
    monkeypatch.setattr(arena_mod.random, "randrange", lambda n: 99)  # force ADVANCE
    party = Party()
    party.add_member(Character("Hero", "M", hp=500, max_hp=500))
    dead = Character("Corpse", "M", hp=0, max_hp=100, status=Status.DEAD)
    party.add_member(dead)

    arena = CombatArena(party, load_combat_map(asset_mgr, "CNFLCT_G.ULT"),
                        asset_mgr=asset_mgr, monster_count=1)
    corpse_pos = arena.player_positions[1]
    # Hero stands just beyond the corpse along the monster's line of approach.
    mdx = corpse_pos[0] - arena.monsters[0].x
    mdy = corpse_pos[1] - arena.monsters[0].y
    hero_x = corpse_pos[0] + (1 if mdx > 0 else -1 if mdx < 0 else 0)
    hero_y = corpse_pos[1] + (1 if mdy > 0 else -1 if mdy < 0 else 0)
    arena.player_positions[0] = (hero_x, hero_y)
    arena.party.members[0].x, arena.party.members[0].y = hero_x, hero_y
    arena.monsters[0].basehp = 4

    res = arena._execute_single_monster_ai(arena.monsters[0])
    assert (arena.monsters[0].x, arena.monsters[0].y) != corpse_pos  # never steps on
    if res is not None:
        assert res.action_type != "flee"


def test_teleport_step_never_lands_on_occupied_tile(asset_mgr, monkeypatch):
    """Java case TELEPORT (CombatScreen.java:748-768) places no occupancy
    condition on the random guide tile; the actual displacement is the
    moveCreature masked step toward it, and THAT step is subject to
    hasBlockingCombatPlayerAt / hasBlockingCreatureAt — so the monster can
    never end up sharing a member's or another creature's tile."""
    monkeypatch.setattr(arena_mod.random, "randrange", lambda n: 0)  # force TELEPORT
    party = build_party()
    arena = CombatArena(party, load_combat_map(asset_mgr, "CNFLCT_G.ULT"),
                        asset_mgr=asset_mgr, monster_count=2)
    arena.player_positions[0] = (5, 5)
    arena.monsters[0].x, arena.monsters[0].y = 5, 8
    arena.monsters[1].x, arena.monsters[1].y = 5, 7  # the north step is occupied

    for _ in range(50):
        arena._execute_single_monster_ai(arena.monsters[0])
        tiles = [arena.player_positions[0]] + [(m.x, m.y) for m in arena.monsters]
        assert len(set(tiles)) == len(tiles)


# --- pending item 4 (Java CombatScreen creature specials) ---------------------


def test_negating_creature_sets_player_negate_aura(asset_mgr, conflict_map, monkeypatch):
    """Java CombatScreen.creatureAction:692-694 — every creature turn whose
    creature has casts == "negate" (Creature.java:441-442) sets the
    player-side NEGATE aura for 2 turns (Context.setAura, Context.java:207).
    Passing a HIT is not required: the set is unconditional."""
    monkeypatch.setattr(arena_mod.random, "randrange", lambda n: 99)  # no teleport/ranged
    party = build_party(hp=1000)
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1)
    arena.monsters[0].definition = CreatureDef(
        id=1, name="Negator", tile="wisp", basehp=48, casts="negate"
    )
    arena.player_positions[0] = (5, 5)
    arena.monsters[0].x, arena.monsters[0].y = 5, 4
    assert party.aura.get_type() == AuraType.NONE

    res = arena._execute_single_monster_ai(arena.monsters[0])

    assert res is not None  # it also still took its melee action
    assert party.aura.get_type() == AuraType.NEGATE
    assert party.aura.get_duration() == 2


def test_non_negating_creature_leaves_aura_alone(asset_mgr, conflict_map, monkeypatch):
    monkeypatch.setattr(arena_mod.random, "randrange", lambda n: 99)
    party = build_party(hp=1000)
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1)
    arena.player_positions[0] = (5, 8)
    arena.monsters[0].x, arena.monsters[0].y = 5, 4

    arena._execute_single_monster_ai(arena.monsters[0])

    assert party.aura.get_type() == AuraType.NONE


def test_negating_creature_sets_aura_even_under_jinx(asset_mgr, conflict_map, monkeypatch):
    """Java CombatScreen.java:692-694 sits BEFORE the no-target return (707-
    709): a JINX aura (nearestPartyMember yields nothing, CombatScreen.java:
    812) still lets the negater set the aura."""
    monkeypatch.setattr(arena_mod.random, "randrange", lambda n: 99)
    party = build_party(hp=1000)
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1)
    arena.monsters[0].definition = CreatureDef(
        id=1, name="Negator", tile="wisp", basehp=48, casts="negate"
    )
    party.aura.set(AuraType.JINX, 4)
    arena.player_positions[0] = (5, 8)
    arena.monsters[0].x, arena.monsters[0].y = 5, 4

    res = arena._execute_single_monster_ai(arena.monsters[0])

    assert res is None  # no action under JINX
    assert party.aura.get_type() == AuraType.NEGATE
    assert party.aura.get_duration() == 2


def test_negate_aura_survives_the_round_aura_tick(asset_mgr, conflict_map, monkeypatch):
    """Round order (Java CombatScreen.finishTurn:472-502): aura.passTurn ticks
    the aura down BEFORE the creature-action sequence, so a constant negater
    re-arms it (2) every round — spellcasting stays blocked round after round."""
    monkeypatch.setattr(arena_mod.random, "randrange", lambda n: 99)
    party = build_party(hp=1000)
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1)
    arena.monsters[0].definition = CreatureDef(
        id=1, name="Negator", tile="wisp", basehp=48, casts="negate"
    )
    arena.player_positions[0] = (5, 8)
    arena.monsters[0].x, arena.monsters[0].y = 5, 3

    for _ in range(3):
        arena.execute_monster_turns()
        # pass_turn ran first (tick to 1), then the negater re-set it to 2.
        assert party.aura.get_type() == AuraType.NEGATE
        assert party.aura.get_duration() == 2


def test_camouflage_creature_spawns_hidden(asset_mgr):
    """Java Creature copy-ctor (Creature.java:70-72): isVisible = !camouflage,
    so camouflaged combat spawns land on the board hidden."""
    from py_exodus.combat.arena import CombatMonster

    visible = CombatMonster(
        CreatureDef(id=2, name="Owl", tile="orc", basehp=48), 1, 1
    )
    camo = CombatMonster(
        CreatureDef(id=3, name="Shade", tile="orc", basehp=48, camouflage=True), 1, 1
    )
    assert visible.visible is True
    assert camo.visible is False


def test_camouflage_hides_at_distance_and_takes_no_action(asset_mgr, conflict_map, monkeypatch):
    monkeypatch.setattr(arena_mod.random, "randrange", lambda n: 99)  # ADVANCE path
    party = build_party(hp=1000)
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1)
    arena.monsters[0].definition = CreatureDef(
        id=4, name="Shade", tile="orc", basehp=48, camouflage=True
    )
    arena.monsters[0].visible = True  # started revealed; far now
    arena.player_positions[0] = (5, 5)
    arena.monsters[0].x, arena.monsters[0].y = 0, 0  # movement distance 10

    res = arena._execute_single_monster_ai(arena.monsters[0])

    assert res is None
    assert arena.monsters[0].visible is False


def test_camouflage_reveals_when_within_5_then_acts(asset_mgr, conflict_map, monkeypatch):
    """Java CombatScreen.java:867-870 — dist < 5 reveals; the visible creature
    then goes on to take its chosen action in the SAME turn."""
    monkeypatch.setattr(resolver_mod, "roll_hit", lambda *a, **k: False)
    monkeypatch.setattr(arena_mod.random, "randrange", lambda n: 99)
    party = build_party(hp=1000)
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1)
    arena.monsters[0].definition = CreatureDef(
        id=5, name="Shade", tile="orc", basehp=48, camouflage=True
    )
    arena.player_positions[0] = (5, 5)
    arena.monsters[0].x, arena.monsters[0].y = 5, 4  # movement distance 1

    res = arena._execute_single_monster_ai(arena.monsters[0])

    assert arena.monsters[0].visible is True
    assert res is not None and res.action_type == "attack"


def test_hidden_camouflage_monster_is_never_rendered(asset_mgr, conflict_map, pygame_setup):
    """Java CombatScreen.java:236-238 — the batch loop skips creatures whose
    getVisible() is false, so a hidden camouflaged monster draws nothing; the
    same loop still draws once it has revealed."""
    import pygame as pg
    from py_exodus.screens.combat_screen import CombatScreen

    class _SpySurface(pg.Surface):
        def __init__(self, size):
            super().__init__(size)
            self.blits = []

        def blit(self, src, *a, **k):
            self.blits.append(src)
            return super().blit(src, *a, **k)

    party = Party()
    hero = Character("Hero", "M", hp=100, max_hp=100)
    party.add_member(hero)
    combat = CombatScreen(
        party=party, combat_map=conflict_map, creature_tile="orc",
        asset_mgr=asset_mgr, monster_count=1,
    )
    monster = combat.arena.monsters[0]
    monster.definition = CreatureDef(
        id=6, name="Shade", tile="orc", basehp=48, camouflage=True
    )
    combat.arena.creature_def = monster.definition
    monster.visible = False

    # A distinct marker tile image: blits of it stand out from HUD text.
    marker = pg.Surface((24, 24))
    asset_mgr.get_tile_surface = lambda name, _m=marker: _m

    surface = _SpySurface((11 * 24, 11 * 24))
    combat._render_monsters(surface)
    assert marker not in surface.blits

    monster.visible = True
    combat._render_monsters(surface)
    assert marker in surface.blits


# --- (l) canonical combat strings — pending item 3 ----------------------------
# Java truth table (log/hud sites):
#   Utils.java:853            "Missed!"
#   Utils.java:841-845        (wrong range: silent — returns NONE)
#   Utils.java:837-839        (no creature on the traced tile: silent — NONE)
#   Utils.java:628            "%s Killed! Exp. %d"   (byplayer kill)
#   Utils.java:634-650        "%s Fleeing!" / "%s Critical!" /
#                             "%s Heavily Wounded!" / "%s Lightly Wounded!" /
#                             "%s Barely Wounded!"   (surviving hit)
#   Creature.java:390-401     wound tiers vs basehp//4, basehp//2, 3*basehp//4
#   CombatScreen.java:292     "Pass"
#   SpellUtil.java:58         "Thou dost not have enough magic points!"
#   CombatScreen.java:995-997 ready/wear "Failed!" / "Success!"
#   GameScreen.java:423/434   "Victory!" / "Battle is lost!"
#   GameScreen.java:433-446   party wipe: NO string (straight to partyDeath)
# Java names the creature only — the attacker and the raw damage number are
# never printed.


def _string_monster(name="Orc", basehp=48, exp=7, **extra):
    return CombatMonster(
        CreatureDef(id=99, name=name, tile="orc", basehp=basehp, exp=exp),
        0,
        0,
    )


def test_wound_string_table_matches_java(monkeypatch):
    """Utils.java:634-650 + Creature.java:390-401 tier table, hp vs basehp."""
    m = _string_monster(name="Orc", basehp=48, exp=7)
    # Creature.java:391-393, strict < comparisons: crit<12, heavy<24,
    # light<36.
    for hp, expected in [
        (48, "Orc Barely Wounded!"),
        (36, "Orc Barely Wounded!"),
        (35, "Orc Lightly Wounded!"),
        (24, "Orc Lightly Wounded!"),
        (23, "Orc Heavily Wounded!"),
        (12, "Orc Heavily Wounded!"),
        (11, "Orc Critical!"),
    ]:
        m.hp = hp
        assert resolver_mod.creature_wound_message(m) == expected


def test_player_attack_kill_string(monkeypatch):
    """Kill: `"%s Killed! Exp. %d"` (Utils.java:628) — no damage number, no
    attacker name (the old `struck ... for N dmg - Killed! (+N EXP)` lines are
    invented)."""
    from py_exodus.combat.resolver import resolve_player_attack

    m = _string_monster(name="Orc", basehp=8, exp=7)
    m.hp = 3
    hero = Character("Hero", "M", hp=100, max_hp=100)
    hero.dex = 30
    monkeypatch.setattr(resolver_mod, "roll_hit", lambda *a, **k: True)
    monkeypatch.setattr(resolver_mod, "calculate_player_damage", lambda *a, **k: 10)
    res = resolve_player_attack(character=hero, weapon_def=None, target_monster=m)
    assert res.killed
    assert res.message == "Orc Killed! Exp. 7"


def test_player_attack_miss_and_range_strings(monkeypatch):
    """MISS prints exactly "Missed!" (Utils.java:853); a wrong-range shot is
    silent (Utils.java:841-845)."""
    from py_exodus.combat.resolver import resolve_player_attack
    from py_exodus.entities.defs import WeaponDef

    m = _string_monster(name="Orc")
    m.hp = m.max_hp
    hero = Character("Hero", "M", hp=100, max_hp=100)
    hero.dex = 30
    monkeypatch.setattr(resolver_mod, "roll_hit", lambda *a, **k: False)
    res = resolve_player_attack(character=hero, weapon_def=None, target_monster=m)
    assert res.message == "Missed!"

    sword = WeaponDef(type="sword", name="Sword", dmin=4, dmax=8, range=1)
    res = resolve_player_attack(
        character=hero, weapon_def=sword, target_monster=m, distance=3
    )
    assert res.result.name == "MISS"
    assert res.message == ""


def test_guard_hit_cites_wound_tier(monkeypatch):
    """The 0-damage guard/LB branch (GBC battle.c:646-648) has NO GBC text —
    battle.c:640 only plays showmonsterhit's "HIT" sprite — so Java governs:
    damageCreature's wound-status line (Utils.java:650, HP write skipped)."""
    from py_exodus.combat.resolver import resolve_player_attack

    guard = CombatMonster(
        CreatureDef(id=98, name="Guard", tile="guard", basehp=40, exp=10), 0, 0
    )
    guard.hp = max_hp = 40
    hero = Character("Hero", "M", hp=100, max_hp=100)
    hero.dex = 30
    monkeypatch.setattr(resolver_mod, "roll_hit", lambda *a, **k: True)
    res = resolve_player_attack(
        character=hero, weapon_def=None, target_monster=guard
    )
    assert res.hit and res.damage == 0 and not res.killed
    assert res.message == "Guard Barely Wounded!"
    assert guard.hp == max_hp


def test_arena_pass_string(asset_mgr, conflict_map):
    """CombatScreen.java:292 — the SPACE pass logs exactly "Pass"."""
    party = build_party(1)
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1)
    res = arena.execute_turn(Action.pass_turn())
    assert res.message == "Pass"


def test_swing_at_nothing_is_silent(asset_mgr, conflict_map):
    """A traced shot / melee step with no creature on its tile logs nothing
    (Utils.java:837-845: attackAt returns NONE without a hud.add)."""
    party = build_party(1)
    arena = CombatArena(party, conflict_map, asset_mgr=asset_mgr, monster_count=1)
    member = party.members[0]
    arena.player_positions[0] = (5, 7)
    # No monster adjacent to (5,7): the melee tile is empty.
    for m in arena.monsters:
        m.x, m.y = (10, 10)
    res = arena.execute_turn(Action.attack(Direction.EAST))
    # EAST from (5,7) targets (6,7); it may hold a wall/other tile — as long
    # as no monster was reached, Java logs nothing.
    assert not any(m.x == 6 and m.y == 7 for m in arena.monsters)
    assert res.message == ""


def test_spell_hit_uses_wound_string(monkeypatch, asset_mgr, conflict_map):
    """Java castAt has no own text — the spell kill goes through the same
    dealDamage → damageCreature line (Utils.java:628)."""
    from py_exodus.combat import magic
    from py_exodus.combat.magic import _apply_projectile_attack, Spell

    arena = CombatArena(build_party(1), conflict_map, asset_mgr=asset_mgr, monster_count=1)
    m = arena.monsters[0]
    m.definition = CreatureDef(id=97, name="Orc", tile="orc", basehp=8, exp=7)
    m.exp = 7
    # The caster sits one tile below the monster: FULGAR (NORTH) rays it.
    arena.player_positions[0] = (m.x, m.y + 1)
    m.hp = 3
    caster = arena.party.members[0]
    caster.character.name = "Hero"
    monkeypatch.setattr(magic, "_caster_damage", lambda low, high: low)
    res = _apply_projectile_attack(
        spell=Spell.FULGAR,
        caster_char=caster.character,
        caster_entity=caster,
        target_dir=Direction.NORTH,
        arena=arena,
    )
    assert res.hit and m.is_dead
    assert res.message == "Orc Killed! Exp. 7"


def test_wipe_logs_no_game_event_string(asset_mgr, conflict_map, monkeypatch):
    """GameScreen.java:433-446: a party wipe branches straight to
    partyDeath() with NO log line (the old `DEFEAT! Thy party has fallen.`
    was invented). py keeps only its `"Press Enter to continue."` dismissal
    prompt. Java's win line ("Victory!", GameScreen.java:423) is pinned by
    test_game_loop; "Battle is lost!" (GameScreen.java:434) belongs to the
    town-return path, not the combat log."""
    from py_exodus.screens.combat_screen import CombatScreen

    combat = CombatScreen(
        party=build_party(1),
        combat_map=conflict_map,
        creature_tile="orc",
        asset_mgr=asset_mgr,
        monster_count=1,
    )

    def _wipe(action):
        combat.arena.is_defeat = True
        combat.arena.is_finished = True
        combat.log_messages = []
        return ActionResult(success=True, action=action, message="Pass")

    from py_exodus.combat.arena import ActionResult

    monkeypatch.setattr(combat.arena, "execute_turn", _wipe)
    monkeypatch.setattr(combat, "check_party_death", lambda: None)
    combat._execute_action(Action.pass_turn())
    assert not any("DEFEAT" in msg for msg in combat.text_log.history)
    assert "Press Enter to continue." in combat.text_log.history
