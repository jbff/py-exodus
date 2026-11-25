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
    resolve_monster_ranged_attack,
    resolve_player_attack,
    try_monster_magic_poke,
)
from py_exodus.constants import ArmorType, Status, WeaponType
from py_exodus.entities.character import Character
from py_exodus.entities.defs import CreatureDef

THIEF = CreatureDef(id=12, name="Thief", tile="thief", basehp=80, steals="equipment")
PINCHER = CreatureDef(id=17, name="Pincher", tile="pincher", basehp=144, poisons=True)
MUNCHER = CreatureDef(id=1, name="Muncher", tile="orc", basehp=48, steals="food")
CUTPURSE = CreatureDef(id=2, name="Cutpurse", tile="orc", basehp=48, steals="gold")
ORC = CreatureDef(id=3, name="Orc", tile="orc", basehp=48)

WIZARD = CreatureDef(id=16, name="Wizard", tile="wizard", basehp=112,
                     ranged=True, ranged_hit_tile="magic")

GUARD = CreatureDef(id=6, name="Guard", tile="guard", basehp=128)
LORD_BRITISH = CreatureDef(id=7, name="Lord British", tile="lord_british",
                           basehp=255, invincible=True)


def _forced_hit(monkeypatch, damage=1):
    """Force the monster hit roll and damage so only the on-hit specials vary
    (LairWare roll/damage since 2026-11-22; the Java seams stay patched for
    the player-side callers)."""
    monkeypatch.setattr(resolver_mod, "roll_hit", lambda *a, **k: True)
    monkeypatch.setattr(resolver_mod, "calculate_monster_damage", lambda basehp=48: damage)
    monkeypatch.setattr(resolver_mod, "lw_monster_hits", lambda *a, **k: True)
    monkeypatch.setattr(resolver_mod, "lw_monster_damage_roll", lambda *a, **k: damage)


def _attacker():
    return Character("Hero", "M", hp=999, max_hp=999, dexterity=40)


def _forced_hit_flat(monkeypatch, damage):
    """_forced_hit with the GBC terrain bonus zeroed, so `damage` is exact."""
    _forced_hit(monkeypatch, damage=damage)
    monkeypatch.setattr(
        resolver_mod, "monster_damage_bonus", lambda context_map_id=None: 0
    )


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


def test_thief_theft_carries_pilfered_message(monkeypatch):
    """GBC battle3.c:288/298 — the writegamemessage(pilfered) text. The
    resolution carries "PILFERED!" on an applied equipment theft so the
    arena log pipeline surfaces it; every other melee outcome stays silent
    (Java CombatScreen.java:723-743 logs nothing for the melee branch)."""
    _forced_hit(monkeypatch)
    random.seed(20261114)
    saw_theft = False
    for _ in range(300):
        member = _stocked_member()
        res = resolve_monster_attack(
            monster=CombatMonster(THIEF, 0, 0), target_player=member
        )
        if res.stolen_item is not None:
            assert res.message == "PILFERED!"
            saw_theft = True
        else:
            assert res.message == ""
    assert saw_theft


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


def test_poisoner_melee_hit_carries_poisoned_message(monkeypatch):
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14), pending item 22: after
    the 1-in-4 melee poison lands GBC posts writegamemessage(poisoned)
    printing "POISONED!" (battle3.c:257); Java's melee branch logs nothing
    (CombatScreen.java:720-748), so the GBC line is adopted like PILFERED!.
    Only an actual poisoning carries the text: a non-poisoner's hit and a
    poison roll that did not fire stay silent."""
    _forced_hit(monkeypatch)
    monster = CombatMonster(PINCHER, 0, 0)
    real_randrange = resolver_mod.random.randrange

    def forced_poison(n):
        # Zero out every roll the code makes on this path — for the
        # poisoner/ordinary monsters under test that is only the 1-in-4
        # poison roll, so poison lands on every surviving hit.
        return 0 if n == 4 else real_randrange(n)

    monkeypatch.setattr(resolver_mod.random, "randrange", forced_poison)
    member = Character("Hero", "M", hp=999, max_hp=999)
    res = resolve_monster_attack(monster=monster, target_player=member)
    assert res.poisoned
    assert member.status == Status.POISONED
    assert res.message == "POISONED!"

    res = resolve_monster_attack(monster=CombatMonster(ORC, 0, 0), target_player=member)
    assert res.hit and not res.poisoned
    assert res.message == ""


def test_already_poisoned_hit_stays_silent(monkeypatch):
    """GBC battle3.c:272-277 suppresses the roll for an already-POISONED
    target — no second poison, therefore no "POISONED!" line."""
    _forced_hit(monkeypatch)
    monkeypatch.setattr(resolver_mod.random, "randrange", lambda n: 0)
    member = Character("Hero", "M", hp=999, max_hp=999)
    member.status = Status.POISONED
    res = resolve_monster_attack(monster=CombatMonster(PINCHER, 0, 0), target_player=member)
    assert res.hit and not res.poisoned
    assert member.status == Status.POISONED
    assert res.message == ""


def test_poisoning_blow_that_kills_carries_no_message(monkeypatch):
    """A killing blow skips the on-hit specials (no poison, no PILFERED! or
    POISONED! text — GBC evaluates poison only on a surviving hit)."""
    _forced_hit(monkeypatch, damage=9999)
    monkeypatch.setattr(resolver_mod.random, "randrange", lambda n: 0)
    victim = Character("Hero", "M", hp=5, max_hp=5)
    res = resolve_monster_attack(monster=CombatMonster(PINCHER, 0, 0), target_player=victim)
    assert res.killed and not res.poisoned
    assert res.message == ""


def test_roster_never_pairs_poison_with_theft():
    """Collision guard for the shared melee message slot: no creature in the
    roster both poisons and steals, so POISONED! (battle3.c:257) and
    PILFERED! (battle3.c:288/298) can never both fire on the same hit —
    the single `message` field in AttackResolution is sound."""
    import xml.etree.ElementTree as ET
    from pathlib import Path

    xml_path = Path(__file__).resolve().parent.parent / "assets" / "xml" / "creatures.xml"
    for elem in ET.parse(xml_path).getroot().iter("creature"):
        if (elem.get("poisons") or "").lower() == "true":
            assert elem.get("steals") is None, elem.get("name")


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


def test_lord_british_takes_zero_damage(monkeypatch):
    """LairWare DamageMonster (UltimaSpellCombat.c:738): `if (gMonType !=
    0x26) { /* not Lord British, har har */` - a landed player hit on Lord
    British deals 0 and never kills."""
    monkeypatch.setattr(resolver_mod, "roll_hit", lambda *a, **k: True)
    monster = CombatMonster(LORD_BRITISH, 0, 0)
    res = resolve_player_attack(
        character=_attacker(), weapon_def=None, target_monster=monster
    )
    assert res.hit and res.damage == 0 and not res.killed
    assert res.result.name == "HIT"
    assert monster.hp == monster.max_hp
    assert not monster.is_dead
    assert res.message  # 0-damage immunity still reports a message


def test_guard_takes_damage_across_seeded_rolls():
    """LairWare DamageMonster (UltimaSpellCombat.c:734-756) spares only Lord
    British; a guard (gMonType 0x24) loses HP to landed hits (B-11, user
    ruling 2026-11-25), while Lord British never does."""
    guard = CombatMonster(GUARD, 0, 0)
    lb = CombatMonster(LORD_BRITISH, 0, 0)
    random.seed(4242)
    hits = 0
    for _ in range(50):
        if guard.is_dead:
            break
        res = resolve_player_attack(
            character=_attacker(), weapon_def=None, target_monster=guard
        )
        if res.hit:
            hits += 1
            assert res.damage > 0
        resolve_player_attack(character=_attacker(), weapon_def=None, target_monster=lb)
        assert lb.hp == lb.max_hp
    assert hits and guard.hp < guard.max_hp


# --- terrain damage bonus -----------------------------------------------------


def test_monster_damage_bonus_tiers():
    """LairWare (g835E & 3) * 16 (UltimaSpellCombat.c:1226, user ruling
    2026-11-22): Sosaria 0, dungeons 16, towns 32, castles (British, Exodus)
    48, Ambrosia (Party[3] = 255) 48; an unknown context counts as a town."""
    for name in ("PERINIAN", "DARDIN", "MINE", "FIRE", "DOOM", "SNAKE", "TIME"):
        assert monster_damage_bonus(MAP_NAME_TO_ID[name]) == 16
    assert monster_damage_bonus(MAP_NAME_TO_ID["SOSARIA"]) == 0
    for name in ("BRITISH", "EXODUS", "AMBROSIA"):
        assert monster_damage_bonus(MAP_NAME_TO_ID[name]) == 48
    for name in ("LCB", "DAWN", "YEW", "DEATH"):
        assert monster_damage_bonus(MAP_NAME_TO_ID[name]) == 32
    assert monster_damage_bonus(None) == 32


def test_melee_damage_applies_terrain_bonus(monkeypatch):
    """LairWare: monster hit damage adds the location bonus to the roll."""
    _forced_hit(monkeypatch, damage=1)
    monster = CombatMonster(ORC, 0, 0)
    expected_by_name = {
        "MINE": 17,  # 1 + 16 dungeon
        "SOSARIA": 1,  # 1 + 0 Sosaria surface
        "AMBROSIA": 49,  # 1 + 48 Ambrosia
        "BRITISH": 49,  # 1 + 48 Castle British
        "EXODUS": 49,  # 1 + 48 Castle Exodus
        "DAWN": 33,  # 1 + 32 town
        None: 33,  # unknown context counts as a town
    }
    for map_name, want in expected_by_name.items():
        member = Character("Hero", "M", hp=999, max_hp=999)
        context = None if map_name is None else MAP_NAME_TO_ID[map_name]
        res = resolve_monster_attack(
            monster=monster, target_player=member, context_map_id=context
        )
        assert res.damage == want, map_name
        assert member.hp == 999 - want, map_name


# --- GBC no-LOS magic poke ----------------------------------------------------


def _placed_member(x, y, hp=999):
    member = Character("Hero", "M", hp=hp, max_hp=hp)
    member.x, member.y = x, y
    return member


def _randrange_spy(monkeypatch, capture_n):
    """Capture every randrange(<capture_n>) call while passing the rest through."""
    real_randrange = resolver_mod.random.randrange
    captured: list[int] = []

    def spy(n):
        value = real_randrange(n)
        if n == capture_n:
            captured.append(value)
        return value

    monkeypatch.setattr(resolver_mod.random, "randrange", spy)
    return captured


def _force_poke_success(monkeypatch, value=129):
    """randrange(193) & 0x80 — 129 has the bit set, so the blast always fires."""
    real_randrange = resolver_mod.random.randrange

    def spy(n):
        real_value = real_randrange(n)
        return value if n == 193 else real_value

    monkeypatch.setattr(resolver_mod.random, "randrange", spy)


def test_magic_wizard_pokes_distant_members(monkeypatch):
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): with no adjacent member a
    magic creature rolls make_rnd(0xC1)&0x80 (~34%) and, on success, hits a
    RANDOM living member with the normal single-target roll; no bolt trace
    (GBC battle3.c:856-866)."""
    _forced_hit_flat(monkeypatch, damage=9)
    _force_poke_success(monkeypatch)
    random.seed(20261114)
    for _ in range(25):
        near_target = _placed_member(8, 8)
        other = _placed_member(9, 9)
        monster = CombatMonster(WIZARD, 0, 0)
        res = try_monster_magic_poke(
            monster=monster, members=[near_target, other], context_map_id=None
        )
        assert res is not None
        assert res.message == "Magic Blast!"
        assert res.hit
        assert res.killed is False
        # exactly one living member took the single-target 9 damage
        damaged = [m for m in (near_target, other) if m.hp < m.max_hp]
        assert len(damaged) == 1
        assert damaged[0].hp == 999 - 9


def test_magic_poke_rate_is_34_percent_of_193(monkeypatch):
    """blasts === the count of randrange(193) draws with bit 0x80 set ~34%."""
    _forced_hit(monkeypatch, damage=7)
    rolls = _randrange_spy(monkeypatch, 193)
    random.seed(4242)
    blasts = 0
    for _ in range(200):
        res = try_monster_magic_poke(
            monster=CombatMonster(WIZARD, 0, 0),
            members=[_placed_member(8, 8), _placed_member(9, 9)],
        )
        blasts += res is not None
    assert len(rolls) == 200  # one 34% roll per no-adjacent ranged action
    assert blasts == sum(1 for r in rolls if r & 0x80)
    assert 40 <= blasts <= 100  # ~34% of 200 (expected ~67)


def test_failed_poke_roll_falls_through_to_bolt(monkeypatch):
    """A failed make_rnd(0xC1)&0x80 draw leaves the plain bolt behavior."""
    _forced_hit_flat(monkeypatch, damage=7)  # LW bolts take the location bonus too
    real_randrange = resolver_mod.random.randrange
    monkeypatch.setattr(
        resolver_mod.random,
        "randrange",
        lambda n: 0 if n == 193 else real_randrange(n),
    )
    member = _placed_member(8, 8)
    monster = CombatMonster(WIZARD, 0, 0)
    res = try_monster_magic_poke(
        monster=monster, members=[member], context_map_id=None
    )
    assert res is None
    # nothing happened here — the CALLER's bolt path is what acts instead, and
    # it still deals its plain bolt with no blast message:
    bolt = resolve_monster_ranged_attack(
        monster=monster, target_player=member, members=[member]
    )
    assert bolt.message == ""
    assert bolt.damage == 7
    assert member.hp == 999 - 7


def test_non_magic_creature_never_pokes(monkeypatch):
    """Tile outside the magic set: the 34% roll is not even consumed."""
    _forced_hit(monkeypatch, damage=6)
    rolls = _randrange_spy(monkeypatch, 193)
    monster = CombatMonster(ORC, 0, 0)
    assert try_monster_magic_poke(
        monster=monster, members=[_placed_member(8, 8), _placed_member(9, 9)]
    ) is None
    assert rolls == []


def test_adjacent_member_blocks_the_poke(monkeypatch):
    """A living member beside the monster: the bolt path stays untouched."""
    _forced_hit(monkeypatch, damage=6)
    rolls = _randrange_spy(monkeypatch, 193)
    monster = CombatMonster(WIZARD, 0, 0)
    adjacent = _placed_member(1, 0)
    far = _placed_member(9, 9)
    assert try_monster_magic_poke(
        monster=monster, members=[adjacent, far], context_map_id=None
    ) is None
    assert rolls == []


def test_magic_poke_skips_dead_members(monkeypatch):
    """Dead members never take the blast and never soak the random pick."""
    _forced_hit_flat(monkeypatch, damage=9)
    _force_poke_success(monkeypatch)
    random.seed(777)
    for _ in range(25):
        living_a = _placed_member(8, 8)
        living_b = _placed_member(9, 9)
        dead = _placed_member(3, 3, hp=0)
        dead.status = Status.DEAD
        res = try_monster_magic_poke(
            monster=CombatMonster(WIZARD, 0, 0),
            members=[living_a, dead, living_b],
            context_map_id=None,
        )
        assert res is not None and res.message == "Magic Blast!"
        assert dead.hp == 0 and dead.status == Status.DEAD
        damaged = [m for m in (living_a, living_b) if m.hp < m.max_hp]
        assert len(damaged) == 1
        assert damaged[0].hp == 999 - 9


# --- GBC ship-battle cannonfire -----------------------------------------------


def test_ship_battle_cannonfire_hits_every_living_member(monkeypatch):
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): in a ship battle the
    monster ranged branch is cannonfire — every living member takes one
    randrange(78) blow through the damage chokepoint, dead members untouched
    (GBC battle3.c:507-536)."""
    rolls = _randrange_spy(monkeypatch, 78)
    living_a = _placed_member(5, 5)
    living_b = _placed_member(6, 5)
    dead = _placed_member(7, 5, hp=0)
    dead.status = Status.DEAD
    res = resolve_monster_ranged_attack(
        monster=CombatMonster(ORC, 0, 0),
        target_player=living_a,
        ship_battle=True,
        members=[living_a, dead, living_b],
    )
    # Playtest-1 item 4 affordance: the barrage line is followed by one
    # cannonfire hit line per member whose blow dealt damage (a blow that
    # rolls 0 stays silent; the dead member is never hit).
    msg_lines = res.message.split("\n")
    assert msg_lines[0] == "Cannonball barrage!"
    assert len(msg_lines) == 1 + sum(1 for r in rolls if r > 0)
    for line in msg_lines[1:]:
        assert line.startswith("Orc cannonfire hits ") and line.endswith(").")
    assert res.hit and res.result.name == "HIT"
    assert len(rolls) == 2  # one roll per living member, none for the dead one
    assert all(0 <= r < 78 for r in rolls)
    assert living_a.hp == living_a.max_hp - rolls[0]
    assert living_b.hp == living_b.max_hp - rolls[1]
    assert dead.hp == 0 and dead.status == Status.DEAD
    assert res.damage == sum(rolls)
    assert res.killed is False


def test_ship_battle_cannonfire_can_kill_and_reports_it(monkeypatch):
    """A lethal barrage still routes through apply_damage and reports `killed`."""
    rolls = _randrange_spy(monkeypatch, 78)
    real_randrange = resolver_mod.random.randrange

    def spy(n):
        value = real_randrange(n)
        if n == 78:
            rolls.append(value)
            return 77
        return value

    monkeypatch.setattr(resolver_mod.random, "randrange", spy)
    victim = _placed_member(5, 5, hp=10)
    res = resolve_monster_ranged_attack(
        monster=CombatMonster(ORC, 0, 0),
        target_player=victim,
        ship_battle=True,
        members=[victim],
    )
    assert res.message.startswith("Cannonball barrage!")
    # Playtest-1 item 4 affordance: the death rides its own line and the
    # killing blow is reported with its number (77 exactly).
    assert "Hero falls!" in res.message
    assert "Orc cannonfire hits Hero (-77)." in res.message
    assert res.killed
    assert victim.status == Status.DEAD
    assert victim.hp == 0

# --- Task 17 (GBC parity): NECORP weakening halves melee damage ---------------


def test_necorp_weakening_halves_monster_melee_damage(monkeypatch):
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): a NECORP-weakened
    creature deals half its melee damage. GBC battle.c:1361-1373 sets the target
    monster hp=5 AND monsterpower=10; GBC monsterpower scales the creature's
    damage output, so the py-side approximation applies the debuff after the
    terrain bonus — the total (roll + bonus) is halved, floor division, no
    randomness. Ranged bolts are not affected (GBC's monsterpower feeds the
    melee path)."""
    _forced_hit_flat(monkeypatch, damage=11)
    monster = CombatMonster(ORC, 0, 0)
    monster.weakened = True
    member = Character("Hero", "M", hp=999, max_hp=999)
    res = resolve_monster_attack(monster=monster, target_player=member)
    assert res.damage == 5  # (11 + 0) // 2 — halved after the terrain bonus
    assert member.hp == 999 - 5
    assert not res.killed


def test_unweakened_monster_melee_damage_is_untouched(monkeypatch):
    """The weakened flag defaults False and a plain monster never halves."""
    _forced_hit_flat(monkeypatch, damage=11)
    monster = CombatMonster(ORC, 0, 0)
    assert monster.weakened is False
    member = Character("Hero", "M", hp=999, max_hp=999)
    res = resolve_monster_attack(monster=monster, target_player=member)
    assert res.damage == 11
    assert member.hp == 999 - 11
