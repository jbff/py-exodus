"""Task 1 (GBC parity) — creature on-hit specials in monster melee resolution.

USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): the thief steals equipment
and poisoner creatures poison on melee hits, per the GBC port
(battle3.c:279-301 theft, battle3.c:267-277 poison) instead of Java
(CombatScreen.java:733-743 — food/gold only, no poison).
"""
import random

import pytest

from py_exodus.assets import MAP_NAME_TO_ID
from py_exodus.combat import resolver as resolver_mod
from py_exodus.combat.arena import CombatMonster
from py_exodus.combat.resolver import (
    monster_damage_bonus,
    resolve_monster_attack,
    resolve_player_attack,
)
from py_exodus.constants import ArmorType, Status, WeaponType
from py_exodus.entities.character import Character
from py_exodus.entities.defs import CreatureDef

THIEF = CreatureDef(id=12, name="Thief", tile="thief", basehp=80, steals="equipment")
PINCHER = CreatureDef(id=17, name="Pincher", tile="pincher", basehp=144, poisons=True)
MUNCHER = CreatureDef(id=1, name="Muncher", tile="orc", basehp=48, steals="food")
CUTPURSE = CreatureDef(id=2, name="Cutpurse", tile="orc", basehp=48, steals="gold")
ORC = CreatureDef(id=3, name="Orc", tile="orc", basehp=48)

GUARD = CreatureDef(id=6, name="Guard", tile="guard", basehp=128)
LORD_BRITISH = CreatureDef(id=7, name="Lord British", tile="lord_british",
                           basehp=255, invincible=True)


def _forced_hit(monkeypatch, damage=1):
    """Force the melee hit roll and damage so only the on-hit specials vary."""
    monkeypatch.setattr(resolver_mod, "roll_hit", lambda *a, **k: True)
    monkeypatch.setattr(resolver_mod, "calculate_monster_damage", lambda basehp=48: damage)


def _attacker():
    return Character("Hero", "M", hp=999, max_hp=999, dexterity=40)


def _stocked_member():
    member = Character("Hero", "M", hp=999, max_hp=999)
    member.weapons[WeaponType.DAGGER] = 2
    member.weapons[WeaponType.SWORD] = 1
    member.armors[ArmorType.CLOTH] = 1
    member.armors[ArmorType.CHAIN] = 3
    return member


# --- thief equipment theft ---------------------------------------------------


def test_thief_steals_armor_or_weapon_from_inventory(monkeypatch):
    """GBC battle3.c:280-303 — thief picks armor (1-in-8 slot) or weapon
    (1-in-16 slot) by a 50/50 roll; a hit slot decrements one owned stack."""
    _forced_hit(monkeypatch)
    random.seed(20261114)
    monster = CombatMonster(THIEF, 0, 0)
    thefts: list[str] = []
    for _ in range(200):
        member = _stocked_member()
        weapons_before = dict(member.weapons)
        armors_before = dict(member.armors)
        res = resolve_monster_attack(monster=monster, target_player=member)
        weapons_after = dict(member.weapons)
        armors_after = dict(member.armors)
        if res.stolen_item is None:
            assert weapons_after == weapons_before
            assert armors_after == armors_before
        else:
            assert res.stolen_item in ("weapon", "armor")
            if res.stolen_item == "weapon":
                assert sum(weapons_after.values()) == sum(weapons_before.values()) - 1
                assert armors_after == armors_before
            else:
                assert sum(armors_after.values()) == sum(armors_before.values()) - 1
                assert weapons_after == weapons_before
            thefts.append(res.stolen_item)
    # 200 trials at a combined ~1-in-16 rate: a dry run is astronomically unlikely.
    assert thefts
    assert set(thefts) <= {"weapon", "armor"}


def test_thief_does_not_take_food_or_gold(monkeypatch):
    """The equipment branch must not also trigger the Java food/gold paths."""
    _forced_hit(monkeypatch)
    random.seed(99)
    for _ in range(50):
        member = _stocked_member()
        member.food = 9999
        member.gold = 9999
        res = resolve_monster_attack(monster=CombatMonster(THIEF, 0, 0), target_player=member)
        assert res.stolen_food == 0
        assert res.stolen_gold == 0
        assert member.food == 9999
        assert member.gold == 9999


def test_non_thief_never_strips_equipment(monkeypatch):
    """steals is None or food/gold: no stolen_item, inventory untouched."""
    _forced_hit(monkeypatch)
    random.seed(3)
    for definition in (ORC, MUNCHER, CUTPURSE):
        for _ in range(50):
            member = _stocked_member()
            weapons_before = dict(member.weapons)
            armors_before = dict(member.armors)
            res = resolve_monster_attack(
                monster=CombatMonster(definition, 0, 0), target_player=member
            )
            assert res.stolen_item is None
            assert dict(member.weapons) == weapons_before
            assert dict(member.armors) == armors_before


# --- melee poison -------------------------------------------------------------


def test_pincher_melee_poisons_about_25_percent(monkeypatch):
    """GBC battle3.c:272-277 — poisoners roll make_rnd(0)&3==0 (1-in-4) on a
    surviving hit and set status POISONED."""
    _forced_hit(monkeypatch)
    poison_rolls: list[int] = []
    real_randrange = resolver_mod.random.randrange

    def spy(n):
        value = real_randrange(n)
        if n == 4:
            poison_rolls.append(value)
        return value

    monkeypatch.setattr(resolver_mod.random, "randrange", spy)
    monster = CombatMonster(PINCHER, 0, 0)
    poisoned_hits = 0
    last_poisoned_member = None
    for _ in range(200):
        member = Character("Hero", "M", hp=999, max_hp=999)
        res = resolve_monster_attack(monster=monster, target_player=member)
        assert res.poisoned == (member.status == Status.POISONED)
        if res.poisoned:
            poisoned_hits += 1
            last_poisoned_member = member
    assert len(poison_rolls) == 200  # one 1-in-4 roll per surviving hit
    assert 25 <= poisoned_hits <= 75  # ~25% of 200 (expected 50)
    assert last_poisoned_member is not None
    assert last_poisoned_member.status == Status.POISONED


def test_melee_poison_only_from_poisoners_and_only_on_survivors(monkeypatch):
    """Non-poisoner never poisons; a killing blow leaves no poison behind."""
    _forced_hit(monkeypatch, damage=1)
    member = Character("Hero", "M", hp=999, max_hp=999)
    res = resolve_monster_attack(monster=CombatMonster(ORC, 0, 0), target_player=member)
    assert not res.poisoned
    assert member.status != Status.POISONED

    _forced_hit(monkeypatch, damage=9999)
    victim = Character("Hero", "M", hp=5, max_hp=5)
    res = resolve_monster_attack(monster=CombatMonster(PINCHER, 0, 0), target_player=victim)
    assert res.killed
    assert not res.poisoned
    assert victim.status == Status.DEAD


# --- Java food/gold theft regression ------------------------------------------


def test_food_and_gold_theft_paths_still_behave(monkeypatch):
    """Java CombatScreen.java:733-743 branches survive the GBC additions."""
    _forced_hit(monkeypatch)
    random.seed(11)
    food_dropped = gold_dropped = False
    for _ in range(150):
        food_member = Character("Hero", "M", hp=999, max_hp=999)
        food_member.food = 9999
        gold_member = Character("Hero", "M", hp=999, max_hp=999)
        gold_member.gold = 9999
        res_food = resolve_monster_attack(
            monster=CombatMonster(MUNCHER, 0, 0), target_player=food_member
        )
        res_gold = resolve_monster_attack(
            monster=CombatMonster(CUTPURSE, 0, 0), target_player=gold_member
        )
        assert res_food.stolen_item is None and res_gold.stolen_item is None
        if food_member.food < 9999:
            food_dropped = True
        if gold_member.gold < 9999:
            gold_dropped = True
    assert food_dropped and gold_dropped


# --- guard / Lord British attack immunity -------------------------------------


def test_guard_and_lord_british_take_zero_damage(monkeypatch):
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): a landed player hit vs
    the guard tile (0x18) or Lord British tile (0x19) deals damage 0 and never
    kills — the guard exemption applies in normal mode too, since py-exodus
    has no GBC extragame hard-mode flag (GBC battle.c:646-648)."""
    monkeypatch.setattr(resolver_mod, "roll_hit", lambda *a, **k: True)
    for definition in (GUARD, LORD_BRITISH):
        monster = CombatMonster(definition, 0, 0)
        res = resolve_player_attack(
            character=_attacker(), weapon_def=None, target_monster=monster
        )
        assert res.hit and res.damage == 0 and not res.killed
        assert res.result.name == "HIT"
        assert monster.hp == monster.max_hp
        assert not monster.is_dead
        assert res.message  # 0-damage immunity still reports a message


def test_guard_never_takes_damage_across_seeded_rolls():
    """Unpatched hit rolls: a guard never loses a single HP over many attacks,
    while an ordinary monster beside it still takes damage."""
    guard = CombatMonster(GUARD, 0, 0)
    orc = CombatMonster(ORC, 0, 0)
    random.seed(4242)
    for _ in range(50):
        res = resolve_player_attack(
            character=_attacker(), weapon_def=None, target_monster=guard
        )
        assert guard.hp == guard.max_hp
        assert not res.killed
    # Regression: a mundane enemy is still hurt by the same attack.
    res_orc = resolve_player_attack(
        character=_attacker(), weapon_def=None, target_monster=orc
    )
    assert res_orc.damage > 0 or not res_orc.hit
    assert orc.hp < orc.max_hp or not res_orc.hit


# --- terrain damage bonus -----------------------------------------------------


def test_monster_damage_bonus_tiers():
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): +10 dungeon, +30 surface
    Sosaria/Ambrosia, +20 towns/castles/other interiors — the GBC
    inside/peermap table mapped onto py MAP_NAME_TO_ID ids
    (GBC battle3.c:337-350)."""
    for name in ("PERINIAN", "DARDIN", "MINE", "FIRE", "DOOM", "SNAKE", "TIME"):
        assert monster_damage_bonus(MAP_NAME_TO_ID[name]) == 10
    for name in ("SOSARIA", "AMBROSIA"):
        assert monster_damage_bonus(MAP_NAME_TO_ID[name]) == 30
    for name in ("BRITISH", "LCB", "DAWN", "YEW", "EXODUS"):
        assert monster_damage_bonus(MAP_NAME_TO_ID[name]) == 20
    assert monster_damage_bonus(None) == 20  # unknown context falls to interiors


def test_melee_damage_applies_terrain_bonus(monkeypatch):
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): monster melee damage
    adds the terrain bonus to the roll (GBC battle3.c:337-350)."""
    _forced_hit(monkeypatch, damage=1)
    monster = CombatMonster(ORC, 0, 0)
    expected_by_name = {
        "MINE": 11,  # 1 + 10 dungeon
        "SOSARIA": 31,  # 1 + 30 surface
        "AMBROSIA": 31,
        "EXODUS": 21,  # 1 + 20 castle context
        "DAWN": 21,  # 1 + 20 town
        None: 21,  # unknown/absent context falls to interiors
    }
    for map_name, want in expected_by_name.items():
        member = Character("Hero", "M", hp=999, max_hp=999)
        context = None if map_name is None else MAP_NAME_TO_ID[map_name]
        res = resolve_monster_attack(
            monster=monster, target_player=member, context_map_id=context
        )
        assert res.damage == want, map_name
        assert member.hp == 999 - want, map_name
