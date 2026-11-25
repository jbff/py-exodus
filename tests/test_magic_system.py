"""Tests for Ultima III Magic & Spells System."""
import contextlib
import random as pyrandom

import pytest

from py_exodus.aura import AuraType
from py_exodus.assets import AssetManager
from py_exodus.combat.arena import Action, CombatArena
from py_exodus.combat.magic import SpellResult, cast_spell
from py_exodus.constants import (
    Direction,
    MapType,
    Profession,
    Race,
    Spell,
    Status,
    TileAttrib,
)
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.world.dungeon import DungeonState
from py_exodus.world.loader import MapLoader
from py_exodus.world.map import DungeonMap


@pytest.fixture
def conflict_map(asset_mgr):
    loader = MapLoader(asset_mgr)
    return loader.load_conflict_map("cnflct_a.json")


@contextlib.contextmanager
def seeded_random_state(seed):
    """Seed the shared RNG for a test and restore its draw state afterwards,
    so seeded tests never couple other tests through global random draws."""
    state = pyrandom.getstate()
    pyrandom.seed(seed)
    try:
        yield
    finally:
        pyrandom.setstate(state)


def test_heal_spell():
    """Step 1 from Task 9 brief: Cleric casting SANCTU."""
    c = Character("Cleric1", "F", Race.BOBBIT, Profession.CLERIC)
    c.mp = 20
    c.hp = 50
    c.max_hp = 100
    res = cast_spell(Spell.SANCTU, caster=c, target_dir=None, arena=None, world_map=None)
    assert res.success
    assert c.hp > 50
    assert c.mp < 20


def test_mp_validation():
    """Caster with insufficient MP cannot cast."""
    c = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD)
    c.mp = 2  # Mittar costs 5
    res = cast_spell(Spell.MITTAR, caster=c, target_dir=Direction.NORTH)
    assert not res.success
    assert "magic points" in res.message.lower() or "mp" in res.message.lower()
    assert c.mp == 2


def test_profession_validation():
    """Fighter cannot cast spells."""
    f = Character("Fighter", "M", Race.HUMAN, Profession.FIGHTER)
    f.mp = 50
    res = cast_spell(Spell.SANCTU, caster=f)
    assert not res.success
    assert "cannot cast" in res.message.lower()


def test_cleric_cure_poison():
    """ALCORT (and alias PURITU) cures poisoned status."""
    c = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC)
    c.mp = 50

    target = Character("Target", "M", Race.HUMAN, Profession.FIGHTER, status=Status.POISONED)
    res = cast_spell(Spell.ALCORT, caster=c, target_member=target)
    assert res.success
    assert target.status == Status.GOOD

    # Alias PURITU
    target.status = Status.POISONED
    c.mp = 50
    res_alias = cast_spell("PURITU", caster=c, target_member=target)
    assert res_alias.success
    assert target.status == Status.GOOD


def test_cleric_major_heal():
    """SANCTU_MANI (and alias SURMAND) heals 20-100, capped at max HP.

    USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): no longer a full restore
    to max HP; the heal is randint(0,80)+20 clamped at missing HP (GBC
    menucmd.c:1337-1420; LW UltimaSpellCombat.c:277-348).
    """
    c = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC)
    c.mp = 60

    target = Character("Target", "M", Race.HUMAN, Profession.FIGHTER, hp=20, max_hp=150)
    with seeded_random_state(101):
        res = cast_spell(Spell.SANCTU_MANI, caster=c, target_member=target)
    assert res.success
    assert 20 <= res.healed <= 100
    assert target.hp == 20 + res.healed <= 120


def test_cleric_resurrection():
    """SURMANDUM (and alias ANCRON) resurrects DEAD character to GOOD.

    USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): success is a 75% roll,
    not guaranteed; pinned high here to exercise the success path (GBC
    menucmd.c:1337-1420; LW UltimaSpellCombat.c:277-348).
    """
    import py_exodus.combat.magic as magic

    c = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC)
    c.mp = 75

    target = Character("Target", "M", Race.HUMAN, Profession.FIGHTER, hp=0, status=Status.DEAD)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(magic.random, "random", lambda: 0.5)
        res = cast_spell(Spell.SURMANDUM, caster=c, target_member=target)
    assert res.success
    assert target.status == Status.GOOD
    assert target.hp == 0  # LW UltimaSpellCombat.c:353: HP as it was (ruling Q19)


def test_cleric_recall_ashes():
    """ANJU_SERMANI recalls ASHES to GOOD, HP as it was (LW
    UltimaSpellCombat.c:374-375, user ruling Q19), and deducts 5 wisdom from
    the caster."""
    c = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, wisdom=50)
    c.mp = 80

    target = Character("Target", "M", Race.HUMAN, Profession.FIGHTER, hp=0, status=Status.ASHES)
    res = cast_spell(Spell.ANJU_SERMANI, caster=c, target_member=target)
    assert res.success
    assert target.status == Status.GOOD
    assert target.hp == 0
    assert c.wis == 45


def test_wizard_magic_missile_in_combat(asset_mgr, conflict_map):
    """MITTAR deals RandNum(0, 40) | 0x10 (LW UltimaSpellCombat.c:202)."""
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=50, mp=50)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    m = arena.monsters[0]
    # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): spawn HP is now rolled
    # per battle, floor 15, cap basehp|0x0F (GBC funcs5.c:1546-1554); the old
    # fixed hp=48 sat above MITTAR's 16-24 window, so pin the HP and keep the
    # test purely about the damage dice.
    m.hp = 50
    m.max_hp = 50
    # Place monster directly North of player
    px, py = arena.player_positions[0]
    m.x = px
    m.y = py - 2
    initial_hp = m.hp

    res = cast_spell(Spell.MITTAR, caster=party.members[0], target_dir=Direction.NORTH, arena=arena)
    assert res.success
    assert res.damage in {v | 0x10 for v in range(41)}
    assert m.hp == max(0, initial_hp - res.damage)


def test_wizard_fireball_in_combat(asset_mgr, conflict_map):
    """FULGAR deals a fixed 75 (LW UltimaSpellCombat.c:209)."""
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=50, mp=50)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    m = arena.monsters[0]
    px, py = arena.player_positions[0]
    m.x = px
    m.y = py - 3
    initial_hp = m.hp

    res = cast_spell(Spell.FULGAR, caster=party.members[0], target_dir=Direction.NORTH, arena=arena)
    assert res.success
    assert res.damage == 75
    assert m.hp == max(0, initial_hp - res.damage)


def test_wizard_psionic_blast_in_combat(asset_mgr, conflict_map):
    """MENTAR deals damage based on caster's INT."""
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=60, mp=50)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    m = arena.monsters[0]
    px, py = arena.player_positions[0]
    m.x = px
    m.y = py - 1
    m.hp = 100
    m.max_hp = 100

    res = cast_spell(Spell.MENTAR, caster=party.members[0], target_dir=Direction.NORTH, arena=arena)
    assert res.success
    assert 32 <= res.damage <= 60
    assert m.hp == 100 - res.damage


def test_wizard_death_bolt_in_combat(asset_mgr, conflict_map):
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): DECORP kills the struck
    monster on a hit regardless of hp (GBC battle.c:1285-1296 kill=1) — the
    128-255 roll is the displayed lethal damage."""
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=75)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    m = arena.monsters[0]
    px, py = arena.player_positions[0]
    m.x = px
    m.y = py - 1
    m.hp = 200
    m.max_hp = 200

    res = cast_spell(Spell.DECORP, caster=party.members[0], target_dir=Direction.NORTH, arena=arena)
    assert res.success
    assert res.hit
    assert m.hp == 0 and m.is_dead  # killed regardless of the 200 hp


def test_wizard_stop_time_in_combat(asset_mgr, conflict_map):
    """ALTAIR (ZOMM) sets the QUICKNESS aura for 20 rounds (GBC menucmd.c:1551
    — amended 2026-11-14: 20 rounds per LW UltimaSpellCombat.c:238 + NES
    Bank0F.asm:3329 agreement)."""
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=75)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=2)
    res = cast_spell(Spell.ALTAIR, caster=party.members[0], arena=arena)
    assert res.success
    assert party.aura.get_type() == AuraType.QUICKNESS
    assert party.aura.get_duration() == 20

    # Monster turns are skipped while the QUICKNESS aura is live
    initial_positions = [(m.x, m.y) for m in arena.monsters]
    results = arena.execute_monster_turns()
    assert len(results) == 0
    assert [(m.x, m.y) for m in arena.monsters] == initial_positions


# --- Repond / Pontori (LairWare UltimaSpellCombat.c:190-200, 248-266, 871;
# A-02, user ruling 2026-11-25): one latch per spell per battle, clear at
# combat start, set by the cast after the monster-type test and before its
# 50% roll (RandNum(0, 255) < 128 fails). Past the roll, BigDeath(255):
# each eligible creature dies on its own 75% roll ((rnd)&0x03 != 0) via
# lethal damage against its CURRENT hp; level plays no part.


def _spawn_arena(asset_mgr, conflict_map, creature_tile, monster_count):
    party = Party()
    arena = CombatArena(
        party, conflict_map, creature_tile=creature_tile, asset_mgr=asset_mgr,
        monster_count=monster_count,
    )
    return party, arena


def test_free_spell_latches_clear_at_battle_init(asset_mgr, conflict_map, monkeypatch):
    """No roll at battle start (UltimaSpellCombat.c:871 ``g5521 = g56E7 = 0``)."""
    import py_exodus.combat.arena as arena_mod

    party = Party()
    cleric = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, wisdom=50, mp=50)
    party.add_member(cleric)
    for value in (0, 1):
        monkeypatch.setattr(arena_mod.random, "randrange", lambda n, v=value: v)
        arena = CombatArena(party, conflict_map, creature_tile="skeleton", asset_mgr=asset_mgr, monster_count=1)
        assert arena.repond_latch is False and arena.pontori_latch is False


def test_pontori_kills_nothing_on_a_missed_roll(asset_mgr, conflict_map, monkeypatch):
    """Roll < 128 -> PONTORI fails (UltimaSpellCombat.c:263), executed, no
    EXP, latch spent."""
    import py_exodus.combat.magic as magic

    party, arena = _spawn_arena(asset_mgr, conflict_map, "skeleton", 2)
    cleric = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, wisdom=50, mp=50)
    party.add_member(cleric)

    monkeypatch.setattr(magic.random, "randrange", lambda n: 127)
    res = cast_spell(Spell.PONTORI, caster=cleric, arena=arena)
    assert not res.success
    assert res.message == "FAILED"
    assert res.executed is True
    assert all(not m.is_dead for m in arena.monsters)
    assert cleric.exp == 0
    assert arena.pontori_latch is True


def test_repond_kills_nothing_on_a_missed_roll(asset_mgr, conflict_map, monkeypatch):
    """Roll < 128 -> REPOND fails (UltimaSpellCombat.c:196)."""
    import py_exodus.combat.magic as magic

    party, arena = _spawn_arena(asset_mgr, conflict_map, "orc", 2)
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=50, mp=50)
    party.add_member(wiz)

    monkeypatch.setattr(magic.random, "randrange", lambda n: 127)
    res = cast_spell(Spell.REPOND, caster=wiz, arena=arena)
    assert not res.success
    assert res.message == "FAILED"
    assert res.executed is True
    assert all(not m.is_dead for m in arena.monsters)
    assert wiz.exp == 0
    assert arena.repond_latch is True


def test_spell_result_executed_classification(asset_mgr, conflict_map, monkeypatch):
    """Task 4: the executed flag on SpellResult — default True (effect
    branches ran); the cast_spell pre-execution gates return executed=False."""
    import py_exodus.combat.magic as magic

    # Direct-API mana refusal (SpellUtil.java:57): pre-execution, executed=False
    poor = Character("Broke", "M", Race.FUZZY, Profession.WIZARD, intelligence=50, mp=0)
    res = cast_spell(Spell.MITTAR, caster=poor, target_dir=Direction.NORTH)
    assert not res.success
    assert res.message == "Thou dost not have enough magic points!"
    assert res.executed is False
    assert poor.mp == 0  # mana never moved

    # Successful effect cast: executed=True by default
    rich = Character("Rich", "F", Race.BOBBIT, Profession.CLERIC, wisdom=50, mp=50)
    party = Party()
    party.add_member(rich)
    arena2 = CombatArena(
        party, conflict_map, creature_tile="skeleton", asset_mgr=asset_mgr, monster_count=1
    )
    monkeypatch.setattr(magic.random, "randrange", lambda n: 255)  # the roll passes
    res = cast_spell(Spell.PONTORI, caster=rich, arena=arena2, party=party)
    assert res.success
    assert res.executed is True


def test_pontori_against_undead(asset_mgr, conflict_map, monkeypatch):
    """Past the roll every eligible undead dies on its passing 75% roll via
    lethal damage against CURRENT hp; the latch stays set."""
    import py_exodus.combat.magic as magic

    party, arena = _spawn_arena(asset_mgr, conflict_map, "skeleton", 2)
    cleric = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, wisdom=50, mp=50, level=20)
    party.add_member(cleric)
    # Rolled HP above basehp: the kill must not depend on take_damage(basehp)
    for monster in arena.monsters:
        monster.hp = monster.max_hp = monster.basehp + 9
    monkeypatch.setattr(magic.random, "randrange", lambda n: 255)
    res = cast_spell(Spell.PONTORI, caster=cleric, arena=arena)
    assert res.success
    assert all(m.is_dead for m in arena.monsters)
    assert cleric.exp == sum(m.exp for m in arena.monsters)  # XP via the kill path
    assert arena.pontori_latch is True


def test_masskill_kill_roll_is_75pct_per_monster(asset_mgr, conflict_map, monkeypatch):
    """One (rnd)&0x03 roll per living eligible creature: == 0 spares,
    != 0 kills."""
    import py_exodus.combat.magic as magic

    party, arena = _spawn_arena(asset_mgr, conflict_map, "skeleton", 2)
    cleric = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, wisdom=50, mp=50)
    party.add_member(cleric)

    monkeypatch.setattr(magic.random, "randrange", lambda n: 128)  # passes; 128 & 3 == 0
    res = cast_spell(Spell.PONTORI, caster=cleric, arena=arena)
    assert res.success
    assert all(not m.is_dead for m in arena.monsters)

    # Fresh battle: every roll passes (253 >= 128, 253 & 0x03 != 0)
    party2, arena2 = _spawn_arena(asset_mgr, conflict_map, "skeleton", 2)
    cleric2 = Character("Cleric2", "F", Race.BOBBIT, Profession.CLERIC, wisdom=50, mp=50)
    party2.add_member(cleric2)
    monkeypatch.setattr(magic.random, "randrange", lambda n: 253)
    res2 = cast_spell(Spell.PONTORI, caster=cleric2, arena=arena2)
    assert res2.success
    assert all(m.is_dead for m in arena2.monsters)
    assert cleric2.exp > 0


def test_masskill_75pct_level_independent_seeded(asset_mgr, conflict_map):
    """25 seeded trials: each level casts over 2 undead; level 1 and level 20
    produce identical outcomes; overall about half the casts pass the
    roll, and about 75% of their creatures die."""
    trials = 25
    killed_total = 0
    for i in range(trials):
        counts = []
        for level in (1, 20):
            party = Party()
            cleric = Character(
                "Cleric", "F", Race.BOBBIT, Profession.CLERIC, wisdom=50, mp=50, level=level
            )
            party.add_member(cleric)
            arena = CombatArena(
                party, conflict_map, creature_tile="skeleton", asset_mgr=asset_mgr,
                monster_count=2,
            )
            with seeded_random_state(4000 + i):
                cast_spell(Spell.PONTORI, caster=cleric, arena=arena)
            counts.append(sum(1 for m in arena.monsters if m.is_dead))
        assert counts[0] == counts[1]  # level has no effect
        killed_total += counts[0]
    # 25 trials x 2 undead x 50% x 75% -> expect 18.75 dead
    assert 8 <= killed_total <= 30


def test_repond_against_orcs_free_spell(asset_mgr, conflict_map, monkeypatch):
    """REPOND past its roll destroys only tile=="orc" creatures and is
    limited to one try per combat (LW g5521 latch)."""
    import py_exodus.combat.magic as magic

    party, arena = _spawn_arena(asset_mgr, conflict_map, "orc", 3)
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=50, mp=50)
    party.add_member(wiz)
    for monster in arena.monsters:
        monster.hp = monster.max_hp = monster.basehp + 9

    monkeypatch.setattr(magic.random, "randrange", lambda n: 255)
    res = cast_spell(Spell.REPOND, caster=party.members[0], arena=arena)
    assert res.success
    assert all(m.is_dead for m in arena.monsters)

    # Second attempt fails (LW: the g5521 latch is spent; no orc is left)
    res2 = cast_spell(Spell.REPOND, caster=party.members[0], arena=arena)
    assert not res2.success


def test_repond_spares_non_orc_goblinoids(asset_mgr, conflict_map, monkeypatch):
    """Java's goblinoid set is the single tile "orc" — gremlins/trolls/goblins
    are spared (SpellUtil.spellRepond:462)."""
    import py_exodus.combat.magic as magic
    from py_exodus.entities.defs import CreatureDef

    party, arena = _spawn_arena(asset_mgr, conflict_map, "orc", 2)
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=50, mp=50)
    party.add_member(wiz)
    for m in arena.monsters:
        m.tile = "troll"
        m.definition = CreatureDef(id=2, name="Troll", tile="troll", basehp=48, hp=48, exp=5, undead=False)
    monkeypatch.setattr(magic.random, "randrange", lambda n: 255)
    res = cast_spell(Spell.REPOND, caster=party.members[0], arena=arena)
    # LW UltimaSpellCombat.c:191: no orc, the cast fails (turn spent) and
    # the latch is kept.
    assert not res.success and res.executed
    assert arena.repond_latch is False
    assert all(not m.is_dead for m in arena.monsters)


def test_area_mass_blast_spells(asset_mgr, conflict_map):
    """NOXUM and UNSPEAKABLE damage all monsters in arena (LW BigDeath,
    every 75% roll hit here)."""
    import random as _random
    from unittest import mock
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=90)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=4)
    for m in arena.monsters:
        m.hp = 100
        m.max_hp = 100

    with mock.patch.object(_random, "randrange", lambda *a, **k: 1):
        res = cast_spell(Spell.NOXUM, caster=party.members[0], arena=arena)
    assert res.success
    assert res.targets_affected == 4
    for m in arena.monsters:
        assert m.hp < 100


def test_arena_action_cast_integration(asset_mgr, conflict_map):
    """Action.cast is wired through arena.execute_player_action."""
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=50, mp=50)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    m = arena.monsters[0]
    px, py = arena.player_positions[0]
    m.x = px
    m.y = py - 2

    action = Action.cast(Spell.MITTAR, direction=Direction.NORTH)
    result = arena.execute_player_action(0, action)
    assert result.success
    assert result.spell_res is not None
    assert result.spell_res.success
    assert wiz.mp < 50


def test_exploration_spells_outside_combat():
    """LORUM/LUMINAE flip the boolean torch flag (SpellUtil.java:89-94, 161-163),
    DAG LORUM (LW case 8, wizard I) feeds nobody, and
    the dungeon spells are Dungeon-state operations — party fields are never
    mutated outside a dungeon (old torch_duration / dungeon_level writes are
    gone)."""
    party = Party()
    cleric = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, wisdom=75, mp=80, food=10)
    wizard = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=80, food=10)
    party.add_member(cleric)
    party.add_member(wizard)

    # Light spell (Cleric LUMINAE) — torch boolean, no duration arithmetic
    res_light = cast_spell(Spell.LUMINAE, caster=party.members[0], party=party)
    assert res_light.success
    assert not hasattr(party, "torch_duration") or party.torch_duration == 0

    # Wizard I is LW's DAG LORUM, a light (no food spell any more)
    res_food = cast_spell(Spell.DAG_LORUM, caster=party.members[1], party=party)
    assert res_food.success
    assert cleric.food == 10
    assert wizard.food == 10

    # Dungeon spells are no-ops outside a dungeon (Java's location masks
    # keep them off the surface — they are only reachable there)
    res_up = cast_spell(Spell.REC_SU, caster=party.members[0], party=party)
    assert res_up.success
    assert party.dungeon_level == 0

    party.members[0].mp = 50
    res_exit = cast_spell(Spell.SEQUITU, caster=party.members[0], party=party)
    assert res_exit.success
    assert party.dungeon_level == 0


def test_teleport_spell_in_combat(asset_mgr, conflict_map):
    """DAG_ACRON is world-map only (Constants.locationMask 0x01) and cannot
    blink in combat; Java's spellBlink logs "Outdoors only!" off the surface."""
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=50, mp=50)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    start_pos = arena.player_positions[0]

    res = cast_spell(Spell.DAG_ACRON, caster=party.members[0], arena=arena)
    assert not res.success
    assert "cannot be cast in combat" in res.message
    assert arena.player_positions[0] == start_pos


def test_spell_mp_cost_alias():
    """Verify mp_cost property is available on Spell enum."""
    assert Spell.SANCTU.mp_cost == Spell.SANCTU.cost
    assert Spell.FULGAR.mp_cost == Spell.FULGAR.cost
    assert Spell.DECORP.mp_cost == 55


def test_invalid_direction_in_combat(asset_mgr, conflict_map):
    """Directional spells in combat require a direction."""
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=50, mp=50)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    res = cast_spell(Spell.MITTAR, caster=party.members[0], target_dir=None, arena=arena)
    assert not res.success
    assert "indicate a direction" in res.message.lower()


def test_directional_spell_miss_in_combat(asset_mgr, conflict_map):
    """Directional spell cast into empty space deals 0 damage but succeeds."""
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=50, mp=50)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    # Monster placed far north
    arena.monsters[0].x = 1
    arena.monsters[0].y = 1
    # Player fires East
    res = cast_spell(Spell.MITTAR, caster=party.members[0], target_dir=Direction.EAST, arena=arena)
    assert res.success
    assert res.damage == 0
    # Java castAt: no creature on the ray → NONE silently (Utils.java:813-820);
    # the old "{spell} fired east into empty space." line was invented.
    assert res.message == ""


def test_incapacitated_caster_cannot_cast():
    """Dead or ashes caster cannot cast."""
    dead_wiz = Character("DeadWiz", "M", Race.FUZZY, Profession.WIZARD, status=Status.DEAD, mp=50)
    res = cast_spell(Spell.FULGAR, caster=dead_wiz, target_dir=Direction.NORTH)
    assert not res.success
    assert "cannot cast" in res.message.lower()


def test_targeted_spells_validation_failures():
    """Restorative and life spells validate target condition before MP spend."""
    cleric = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, wisdom=50, mp=90)
    healthy = Character("Healthy", "M", Race.HUMAN, Profession.FIGHTER, hp=100, max_hp=100)
    dead_char = Character("DeadChar", "M", Race.HUMAN, Profession.FIGHTER, hp=0, status=Status.DEAD)
    ash_char = Character("AshChar", "M", Race.HUMAN, Profession.FIGHTER, hp=0, status=Status.ASHES)

    # Healing full HP
    res_heal_full = cast_spell(Spell.SANCTU, caster=cleric, target_member=healthy)
    assert not res_heal_full.success
    assert "full health" in res_heal_full.message.lower()
    assert cleric.mp == 90

    # Major healing dead
    res_major_dead = cast_spell(Spell.SANCTU_MANI, caster=cleric, target_member=dead_char)
    assert not res_major_dead.success
    assert "cannot heal" in res_major_dead.message.lower()

    # Curing non-poisoned
    res_cure = cast_spell(Spell.ALCORT, caster=cleric, target_member=healthy)
    assert not res_cure.success
    assert "not poisoned" in res_cure.message.lower()

    # Resurrecting living character
    res_resurrect = cast_spell(Spell.SURMANDUM, caster=cleric, target_member=healthy)
    assert not res_resurrect.success
    assert "not dead" in res_resurrect.message.lower()

    # Recalling non-ashes character
    res_recall = cast_spell(Spell.ANJU_SERMANI, caster=cleric, target_member=dead_char)
    assert not res_recall.success
    assert "not in ashes" in res_recall.message.lower()


def test_hybrid_professions_casting():
    """Druid, Paladin, Lark have specific casting permissions."""
    druid = Character("Druid", "M", Race.BOBBIT, Profession.DRUID, wisdom=40, intelligence=40, mp=40)
    paladin = Character("Paladin", "M", Race.HUMAN, Profession.PALADIN, wisdom=40, mp=40)
    lark = Character("Lark", "M", Race.ELF, Profession.LARK, intelligence=40, mp=40)

    # Paladin can cast prayer A-H
    paladin.hp = 50
    assert Spell.SANCTU.can_cast(paladin.profession)
    res_paladin = cast_spell(Spell.SANCTU, caster=paladin)
    assert res_paladin.success
    # Heals self
    assert paladin.mp == 30  # 40 - 10
    assert paladin.hp > 50

    # Paladin cannot cast prayer M (EXCUUN)
    assert not Spell.EXCUUN.can_cast(paladin.profession)

    # Lark can cast sorcery A-H
    assert Spell.MITTAR.can_cast(lark.profession)
    # Lark cannot cast sorcery L (DECORP)
    assert not Spell.DECORP.can_cast(lark.profession)


def test_excuun_cleric_death_bolt_in_combat(asset_mgr, conflict_map):
    """Cleric EXCUUN deals 64-255 directional damage."""
    party = Party()
    cleric = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, wisdom=75, mp=75)
    party.add_member(cleric)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    m = arena.monsters[0]
    px, py = arena.player_positions[0]
    m.x = px
    m.y = py - 1
    m.hp = 300

    res = cast_spell(Spell.EXCUUN, caster=party.members[0], target_dir=Direction.NORTH, arena=arena)
    assert res.success
    assert 64 <= res.damage <= 255


def test_unknown_spell_handling():
    """Unknown spell strings fail gracefully."""
    c = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, wisdom=50, mp=50)
    res = cast_spell("NOT_A_REAL_SPELL", caster=c)
    assert not res.success
    assert "unknown spell" in res.message.lower()


def test_spell_letter_code_resolution_by_discipline(asset_mgr, conflict_map, monkeypatch):
    """Cleric casting 'A' resolves to PONTORI, Wizard to REPOND, Druid by chosen discipline."""
    import py_exodus.combat.magic as magic
    from py_exodus.combat.magic import get_castable_spell_types, resolve_spell

    monkeypatch.setattr(magic.random, "randrange", lambda n: 255)  # Pontori's 50% roll passes

    # Disciplines
    assert get_castable_spell_types(Profession.CLERIC) == ["cleric"]
    assert get_castable_spell_types(Profession.WIZARD) == ["wizard"]
    assert get_castable_spell_types(Profession.DRUID) == ["wizard", "cleric"]
    assert get_castable_spell_types(Profession.RANGER) == ["wizard", "cleric"]
    assert get_castable_spell_types(Profession.FIGHTER) == []

    # Resolution by discipline
    assert resolve_spell("A", spell_type="cleric") == Spell.PONTORI
    assert resolve_spell("A", spell_type="wizard") == Spell.REPOND

    # Resolution inferred from caster
    cleric_char = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, wisdom=50, mp=50)
    wiz_char = Character("Mage", "M", Race.FUZZY, Profession.WIZARD, intelligence=50, mp=50)
    assert resolve_spell("A", caster=cleric_char) == Spell.PONTORI
    assert resolve_spell("A", caster=wiz_char) == Spell.REPOND

    # In combat: Cleric casting "A" casts PONTORI, turning undead, NOT REPOND
    party = Party()
    party.add_member(cleric_char)
    arena = CombatArena(party, conflict_map, creature_tile="skeleton", asset_mgr=asset_mgr, monster_count=1)
    res = cast_spell("A", caster=party.members[0], arena=arena)
    assert res.success
    assert res.spell == Spell.PONTORI
    assert "undead" in res.message.lower()


def test_prompt_cast_party_flow():
    """Overland party casting prompts member, discipline (if both), spell, and target."""
    from py_exodus.combat.magic import prompt_cast_party
    from py_exodus.ui.text_log import TextLog

    party = Party()
    cleric = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, wisdom=50, mp=50, hp=100, max_hp=100)
    fighter = Character("Fighter", "M", Race.HUMAN, Profession.FIGHTER, strength=50, hp=30, max_hp=100)
    druid = Character("Druid", "M", Race.BOBBIT, Profession.DRUID, wisdom=50, intelligence=50, mp=50)
    party.add_member(cleric)
    party.add_member(fighter)
    party.add_member(druid)

    log = TextLog()

    # Flow 1: Cleric casts Sanctu (C) on Fighter (2)
    prompt_cast_party(log, party)
    assert "Which member?" in log.current_prompt
    assert log.single_char is True

    # User inputs '1' for Cleric
    log.handle_char("1")
    # Prompt advances to Cleric spell code immediately (no Enter needed)
    assert "Cleric Spell?" in log.current_prompt

    # User inputs 'C' for Sanctu — USER-DIRECTED RULING (2026-11-15): fixed
    # spell letters (B=APPAR_UNEM always; C=SANCTU always), supersedes the
    # getCastables compaction adopted 2026-11-14.
    log.handle_char("C")
    # Prompt advances to target member immediately
    assert "On who?" in log.current_prompt

    # User inputs '2' for Fighter
    log.handle_char("2")
    # Healed! Prompt is complete
    assert not log.is_waiting_for_input
    assert fighter.hp > 30

    # Flow 2: Druid is prompted for [W]izard or [C]leric first
    prompt_cast_party(log, party)
    # Member '3' (Druid)
    log.handle_char("3")
    assert "Spell Type?" in log.current_prompt
    assert "[W]izard or [C]leric" in log.current_prompt

    # Choose 'C' for Cleric
    log.handle_char("C")
    assert "Cleric Spell?" in log.current_prompt


# --- Task 25 (D4): VIEDA peer view and FAL_DIVI cleric re-dispatch ---

def test_vieda_result_requests_gem_view_also_through_fal_divi():
    """VIEDA's result tells the calling screen to open the peer-gem view
    (GBC menucmd.c:1379-1390 — dopeergem(1), the P command's screen without
    the gem payment). Through FAL_DIVI the wizard casts the cleric spell
    itself (LairWare case 9, UltimaSpellCombat.c:231-235, ledger P-20), so
    the same flag comes back: 45 + 55 MP."""
    caster_cleric = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, mp=60)
    caster_wizard = Character("Mage", "M", Race.FUZZY, Profession.WIZARD, intelligence=60, mp=100)

    vieda_res = cast_spell(Spell.VIEDA, caster=caster_cleric)
    assert vieda_res.success
    assert vieda_res.open_gem_view is True
    # Combat keeps the flavor behavior only — the screen, not cast_spell,
    # decides whether a view is possible.
    assert vieda_res.message

    fal_res = cast_spell(Spell.FAL_DIVI, caster=caster_wizard, cleric_spell=Spell.VIEDA)
    assert fal_res.success
    assert fal_res.open_gem_view is True
    assert caster_wizard.mp == 0


def test_fal_divi_asks_the_cleric_letter_of_the_same_caster():
    """FAL_DIVI goes straight to ClericChoose for the same caster (LairWare
    case 9, ledger P-20): no second member prompt. A cleric spell the caster
    cannot pay for after Fal Divi's 45 is ProcessMagic's "M.P. too low!"
    (UltimaSpellCombat.c:98-101), with Fal Divi's MP spent."""
    from py_exodus.combat.magic import prompt_cast_party
    from py_exodus.ui.text_log import TextLog

    party = Party()
    mage = Character("Mage", "M", Race.FUZZY, Profession.WIZARD, intelligence=50, mp=90)
    party.add_member(mage)

    log = TextLog()
    prompts: list[str] = []
    real_prompt = log.prompt

    def _spy_prompt(query, callback, single_char=False):
        prompts.append(query)
        return real_prompt(query, callback, single_char=single_char)

    log.prompt = _spy_prompt  # type: ignore[method-assign]

    prompt_cast_party(log, party)
    log.handle_char("1")  # member 1: the Mage
    assert "Wizard Spell?" in log.current_prompt
    log.handle_char("J")  # FAL_DIVI, its fixed wizard letter
    assert log.current_prompt == "Cleric Spell? (A-P):"
    log.handle_char("L")  # VIEDA: 55 MP, but only 45 left
    assert not log.is_waiting_for_input
    assert "M.P. too low!" in "\n".join(str(line) for line in log.history)
    assert mage.mp == 90 - 45
    assert prompts == [
        "Cast: Which member? (1-4):",
        "Wizard Spell? (A-P):",
        "Cleric Spell? (A-P):",
    ]


def test_fal_divi_in_combat_spends_the_turn(asset_mgr, conflict_map):
    """LairWare case 9 is an ordinary cast in combat: the loop goes on to
    plrdone (ledger P-20). Without a cleric letter nothing more is cast, but
    Fal Divi's 45 MP and the turn are spent."""
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=75)
    party.add_member(wiz)
    arena = CombatArena(party=party, combat_map=conflict_map, creature_tile="orc",
                        asset_mgr=asset_mgr, monster_count=1)
    mp = wiz.mp

    res = arena.execute_player_action(0, Action.cast(Spell.FAL_DIVI))
    assert res.consume_turn
    assert wiz.mp == mp - 45


def test_vieda_outside_combat_view_only_for_non_combat_sites():
    """VIEDA's peer-gem side effect travels on SpellResult and the prompt flow
    invokes the screen's view callback through that flag (the same convention
    as exit_dungeon), so a screen with no view machinery is left untouched."""
    from py_exodus.combat.magic import prompt_cast_party
    from py_exodus.ui.text_log import TextLog

    party = Party()
    cleric = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, wisdom=50, mp=60)
    party.add_member(cleric)

    log = TextLog()
    calls: list[tuple] = []

    prompt_cast_party(log, party, view_callback=lambda: calls.append(("view",)))
    log.handle_char("1")
    log.handle_char("L")  # VIEDA — its FIXED cleric code (USER-DIRECTED RULING 2026-11-15)

    # The screen view callback fired once, off the flag.
    assert calls == [("view",)]
    assert log.is_waiting_for_input is False


def test_appar_unem_disarms_and_gets_chest():
    """Verify APPAR_UNEM safely opens, gets gold, and removes chest without requiring 'G'."""
    party = Party(x=10, y=10, gold=100)
    cleric = Character("Bishop", "M", Race.BOBBIT, Profession.CLERIC, wisdom=50, mp=50)
    party.add_member(cleric)

    # Place a chest at the party's own tile (Java getChest scans exactly cx == x && cy == y)
    party.dynamic_objects.append({"tile": "chest", "x": 10, "y": 10})
    assert len(party.dynamic_objects) == 1

    # Seeded so the GBC 25% fizzle roll (menucmd.c:1311-1313) is a pass:
    # seed 19's first randrange(256) draw is 22 (22 & 0x03 != 0).
    with seeded_random_state(19):
        # Cast APPAR_UNEM (direction prompted then ignored by Java)
        res = cast_spell(Spell.APPAR_UNEM, caster=cleric, party=party, target_dir=Direction.SOUTH)
        assert res.success is True
        assert "The Chest Holds" in res.message
        assert party.gold > 100
        assert len(party.dynamic_objects) == 0

        # Cast again when no chest is nearby ("Not Here!" consumes no roll)
        res2 = cast_spell(Spell.APPAR_UNEM, caster=cleric, party=party, target_dir=Direction.NORTH)
        assert res2.success is False
        assert "Not Here!" in res2.message


def test_appar_unem_gbc_25pct_failure_seeded():
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): with a chest present,
    APPAR_UNEM fails outright ~25% of the time (GBC menucmd.c:1311-1313,
    `(make_rnd(0))&0x03)==0`; LW UltimaSpellCombat.c:268-273 corroborates
    `RandNum(0,255)&0x03`). GBC checks the chest first (menucmd.c:1054-1063),
    so the "Not Here!" path consumes no roll; the tile clear runs after the
    roll passes (menucmd.c:1219-1233), so a failed cast leaves the chest in
    place. Mana is spent on every cast either way (GBC deducts before
    dogetchest, menucmd.c:1309)."""
    party = Party(x=10, y=10, gold=100)
    cleric = Character(
        "Bishop", "M", Race.BOBBIT, Profession.CLERIC, wisdom=50, mp=50, hp=100, max_hp=100
    )
    party.add_member(cleric)

    failures = 0
    with seeded_random_state(2026):
        for _ in range(100):
            party.dynamic_objects.clear()
            party.dynamic_objects.append({"tile": "chest", "x": 10, "y": 10})
            gold_before = party.gold
            cleric.mp = 50

            res = cast_spell(
                Spell.APPAR_UNEM, caster=cleric, party=party, target_dir=Direction.SOUTH
            )

            if res.success:
                assert "The Chest Holds" in res.message
                assert len(party.dynamic_objects) == 0
                assert party.gold > gold_before
            else:
                failures += 1
                # GBC faildat2 (menucmd.c:153-156): "FAILED".
                assert "FAILED" in res.message
                assert "Chest Holds" not in res.message
                # The chest survives a failed spell.
                assert len(party.dynamic_objects) == 1
                assert party.gold == gold_before
            # Mana spent whatever the roll said.
            assert cleric.mp == 45

    # ~25% outright failure, ~75% open normally.
    assert 18 <= failures <= 32
    assert 68 <= 100 - failures <= 82


def test_appar_unem_prompt_flow_never_asks_direction():
    """USER RULING 2026-11-11: APPAR_UNEM gets no direction prompt. Java asks
    "Direction?" then ignores the answer (SpellInputProcessor.java:52-61) —
    the ruling removes the prompt, so selecting the spell dispatches straight
    to the caster's-tile chest effect (SpellUtil.java:140-148).

    The chest is at the party's tile, so the GBC 25% fizzle roll
    (menucmd.c:1311-1313, rand(256) & 0x03) would fire stochastically; the
    randrange stub (1 & 0x03 == 1) pins the fizzle off so the test is purely
    about the prompt flow (mirrors test_sanctu_heals_java_range)."""
    import py_exodus.combat.magic as magic
    from py_exodus.combat.magic import prompt_cast_party
    from py_exodus.ui.text_log import TextLog

    party = Party(x=10, y=10, gold=100)
    cleric = Character("Bishop", "M", Race.BOBBIT, Profession.CLERIC, wisdom=50, mp=50)
    party.add_member(cleric)
    party.dynamic_objects.append({"tile": "chest", "x": 10, "y": 10})

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(magic.random, "randrange", lambda n: 1)  # never fizzles
        log = TextLog()
        prompt_cast_party(log, party)
        log.handle_char("1")  # member 1
        log.handle_char("B")  # APPAR_UNEM — its FIXED B (USER-DIRECTED RULING 2026-11-15)

    # The flow completed without any further prompt — no Direction? step.
    assert not log.is_waiting_for_input
    all_log = "\n".join(str(line) for line in log.history)
    assert "Direction?" not in all_log
    assert "The Chest Holds" in all_log
    assert party.gold > 100
    assert len(party.dynamic_objects) == 0


# --- Task 11: exact Java spell-table rows (audit Part 1) ---

def test_sanctu_heals_java_range():
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): the Java Party.java:417
    heal (75 + rand.nextInt(256) % 25) is replaced by GBC's randint(0,20)+10,
    still capped at missing HP (GBC menucmd.c:1337-1420; LW
    UltimaSpellCombat.c:277-348)."""
    import py_exodus.combat.magic as magic

    c = Character("Cleric1", "F", Race.BOBBIT, Profession.CLERIC, mp=20, hp=50, max_hp=200)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(magic.random, "randint", lambda a, b: b)  # 20 → +10 = 30
        res = cast_spell(Spell.SANCTU, caster=c, party=None, target_member=c)
        assert res.success
        assert res.healed == 30
        assert c.hp == 80

    c2 = Character("Cleric2", "F", Race.BOBBIT, Profession.CLERIC, mp=20, hp=50, max_hp=200)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(magic.random, "randint", lambda a, b: a)  # 0 → +10 = 10
        cast_spell(Spell.SANCTU, caster=c2, party=None, target_member=c2)
        assert c2.hp == 60  # 50 + 10

    # Capped at missing health
    c3 = Character("Cleric3", "F", Race.BOBBIT, Profession.CLERIC, mp=20, hp=95, max_hp=100)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(magic.random, "randint", lambda a, b: b)
        cast_spell(Spell.SANCTU, caster=c3, party=None, target_member=c3)
        assert c3.hp == 100


def test_mentar_max_damage_floor_gone(asset_mgr, conflict_map):
    """Java castAt (Utils.java:816-828): minDamage >= maxDamage → damage is
    maxDamage; there is no max(32, int) floor (SpellUtil.java:108-110)."""
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=15, mp=50)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    m = arena.monsters[0]
    px, py = arena.player_positions[0]
    m.x = px
    m.y = py - 1
    m.hp = 100
    m.max_hp = 100

    res = cast_spell(Spell.MENTAR, caster=party.members[0], target_dir=Direction.NORTH, arena=arena)
    assert res.success
    assert res.damage == 15  # maxDamage = intell, floor gone


def test_mentar_damage_is_intell(asset_mgr, conflict_map, monkeypatch):
    """LW UltimaSpellCombat.c:226: Projectile(chnum, Player[rosNum][20])."""
    import py_exodus.combat.magic as magic

    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=40, mp=50)
    party.add_member(wiz)
    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    m = arena.monsters[0]
    px, py = arena.player_positions[0]
    m.x = px
    m.y = py - 1
    m.hp = 100
    m.max_hp = 100

    monkeypatch.setattr(magic.random, "randint", lambda a, b, hi=None: 34)
    res = cast_spell(Spell.MENTAR, caster=party.members[0], target_dir=Direction.NORTH, arena=arena)
    assert res.success
    assert res.damage == 40


def test_zxkuqyb_kill_roll_per_monster(asset_mgr, conflict_map, monkeypatch):
    """USER-DIRECTED RULING (2026-11-15): ZXKUQYB keeps no BUG — Java's
    hp*(3/4)==0 quirk is not carried. Per LW UltimaSpellCombat.c:355
    BigDeath(255) + :475-495, each living monster is destroyed on its own
    75% kill roll ((RandNum(0,255)&0x03)!=0) routed through the lethal
    take_damage(m.hp) kill path; a failed roll leaves it untouched (no
    damage at all). GBC clericspellsdat agrees: "ZXKUQYB KILL ALL"."""
    import py_exodus.combat.magic as magic

    party = Party()
    cleric = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, wisdom=75, mp=75)
    party.add_member(cleric)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=2)
    arena.monsters[0].hp = 100
    arena.monsters[0].max_hp = 100
    arena.monsters[1].hp = 20
    arena.monsters[1].max_hp = 100

    # Scripted kill rolls: monster 0 rolls 1 → &0x03 != 0 → destroyed;
    # monster 1 rolls 0 → &0x03 == 0 → survives completely untouched.
    rolls = iter([1, 0])
    monkeypatch.setattr(magic.random, "randrange", lambda *a, **k: next(rolls))

    res = cast_spell(Spell.ZXKUQYB, caster=party.members[0], arena=arena)
    assert res.success
    assert res.targets_affected == 1  # only the killed monster counts
    assert arena.monsters[0].is_dead  # 75%-roll kill, not 255 damage
    assert arena.last_monster_death_pos is not None
    assert not arena.monsters[1].is_dead
    assert arena.monsters[1].hp == 20  # failed roll → zero damage dealt
    assert "destroys 1" in res.message


def test_zxkuqyb_seeded_trials_kill_share(asset_mgr, conflict_map, monkeypatch):
    """USER-DIRECTED RULING (2026-11-15): across 50 seeded trials no
    zero-damage hit survives — high-hp monsters die ~75% of casts (never
    0%), and low-hp monsters are no longer insta-hit at 100%: the only
    outcomes per monster are destroyed-by-kill-roll or fully untouched."""
    import py_exodus.combat.magic as magic

    rng = pyrandom.Random(20261115)
    monkeypatch.setattr(magic.random, "randrange", lambda *a, **k: rng.randrange(*a))

    kills_high = 0
    kills_low = 0
    for _ in range(50):
        party = Party()
        cleric = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, wisdom=75, mp=75)
        party.add_member(cleric)
        arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=2)
        arena.monsters[0].hp = 100
        arena.monsters[0].max_hp = 100
        arena.monsters[1].hp = 20
        arena.monsters[1].max_hp = 100
        res = cast_spell(Spell.ZXKUQYB, caster=party.members[0], arena=arena)
        assert res.success
        for m, start_hp in ((arena.monsters[0], 100), (arena.monsters[1], 20)):
            if m.is_dead:
                if start_hp == 100:
                    kills_high += 1
                else:
                    kills_low += 1
            else:
                # a surviving monster took no damage at all
                assert m.hp == start_hp, "zero/partial damage hit must not survive"

    # ~75% kill rate; the old bug (hp>23 → hp*3//4 == 0) never killed the
    # 100-hp monster, and the old 15-dmg floor killed the 20-hp monster on
    # every cast.
    assert 25 <= kills_high <= 50, kills_high
    assert 25 <= kills_low <= 49, kills_low


def test_unspeakable_is_lairware_bigdeath(asset_mgr, conflict_map, monkeypatch):
    """LairWare casts UNSPEAKABLE (the Wizard's nameless P spell) as
    BigDeath(255) like ZXKUQYB (UltimaSpellCombat.c:247, 475-495; user ruling
    2026-11-22): each living monster dies on its own 75% roll
    ((RandNum(0,255)&0x03)!=0) or is left untouched. Java's 1/2-kill,
    hp-23 and hp/2 branches are gone."""
    import py_exodus.combat.magic as magic

    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=75)
    party.add_member(wiz)
    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=2)
    for m in arena.monsters:
        m.hp = m.max_hp = 100
    rolls = iter([1, 0])  # monster 0: &3 != 0 -> dies; monster 1: &3 == 0 -> untouched
    monkeypatch.setattr(magic.random, "randrange", lambda *a, **k: next(rolls))
    res = cast_spell(Spell.UNSPEAKABLE, caster=party.members[0], arena=arena)
    assert res.success
    assert arena.monsters[0].is_dead
    assert arena.monsters[1].hp == 100  # never the old hp-23 / hp/2 wound

def test_dag_lorum_sets_long_light_in_dungeon():
    """LW UltimaSpellCombat.c:227-230: Dag Lorum sets gTorch = 250 (user
    ruling Q21 replaced Java's PABULUM food spell)."""
    from py_exodus.world.dungeon import DungeonState
    from py_exodus.world.map import DungeonMap

    state = DungeonState(DungeonMap(id=1, name="D", width=16, height=16, levels=8),
                         start_x=1, start_y=1, start_z=0)
    state.torchtime = 30
    party = Party()
    party.add_member(Character("A", "F", Race.BOBBIT, Profession.WIZARD, mp=50, food=0))
    res = cast_spell(Spell.DAG_LORUM, caster=party.members[0], party=party, world_map=state)
    assert res.success
    assert state.torchtime == 250
    assert party.members[0].food == 0


def test_fulgar_ignores_fire_resists(asset_mgr, conflict_map):
    """LW Projectile(chnum, 75) (UltimaSpellCombat.c:209) has no resistance:
    Java's castAt fire-resist (Utils.java:815-820) is gone."""
    from py_exodus.entities.defs import CreatureDef

    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=75)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    m = arena.monsters[0]
    px, py = arena.player_positions[0]
    m.x = px
    m.y = py - 1
    m.definition = CreatureDef(
        id=7, name="Ember", tile="orc", basehp=48, hp=48, exp=5, resists="fire")
    m.hp = 100
    m.max_hp = 100

    res = cast_spell(Spell.FULGAR, caster=party.members[0], target_dir=Direction.NORTH, arena=arena)
    assert res.success
    assert res.damage == 75
    assert arena.monsters[0].hp == 25


def test_spell_projectiles_pass_walls(asset_mgr, conflict_map):
    """Spell projectiles trace with weaponCanAttackThroughObjects=true
    (Utils.animateMagicAttack) — a wall between caster and target does not
    stop the bolt (resolver.py:152-159)."""
    from py_exodus.assets import TileDef

    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=75)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    m = arena.monsters[0]
    px, py = arena.player_positions[0]
    m.x = px
    m.y = py - 3
    m.hp = 200
    m.max_hp = 200

    wall = TileDef(index=0x80, name="brick_wall", attribs=TileAttrib.UNWALKABLE)
    conflict_map.set_tile(px, py - 1, wall)
    conflict_map.set_tile(px, py - 2, wall)

    res = cast_spell(Spell.MITTAR, caster=party.members[0], target_dir=Direction.NORTH, arena=arena)
    assert res.success
    assert res.damage > 0
    assert m.hp == 200 - res.damage


def test_dag_acron_rejected_off_the_world_map():
    """DAG_ACRON's location mask is 0x01 (world only); town and dungeon casts
    are refused like any other off-mask spell."""
    c = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=50, mp=50)

    class FakeCityMap:
        map_type = MapType.CITY

    res_city = cast_spell(Spell.DAG_ACRON, caster=c, world_map=FakeCityMap())
    assert not res_city.success

    dmap = DungeonMap(id=1, name="D", width=16, height=16, levels=8)
    state = DungeonState(dmap, start_x=1, start_y=1, start_z=0)
    res_dungeon = cast_spell(Spell.DAG_ACRON, caster=c, world_map=state)
    assert not res_dungeon.success


# --- USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): heal/raise dice tests
# (GBC menucmd.c:1337-1420; LW UltimaSpellCombat.c:277-348)


def test_sanctu_heal_band_10_to_30():
    """SANCTU heals randint(0,20)+10 = 10..30, never clamped when missing >= 30."""
    caster = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, mp=9999, max_mp=9999)
    amounts = []
    with seeded_random_state(7):
        for _ in range(300):
            target = Character("Target", "M", Race.HUMAN, Profession.FIGHTER, hp=1, max_hp=100)
            res = cast_spell(Spell.SANCTU, caster=caster, target_member=target)
            assert res.success
            amounts.append(res.healed)
            assert target.hp == 1 + res.healed
    assert all(10 <= a <= 30 for a in amounts)
    assert min(amounts) == 10
    assert max(amounts) == 30


def test_sanctu_heal_clamped_to_missing_hp():
    """SANCTU still clamps to missing HP (missing 5 → at most +5)."""
    caster = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, mp=9999, max_mp=9999)
    with seeded_random_state(11):
        for _ in range(50):
            target = Character("Target", "M", Race.HUMAN, Profession.FIGHTER, hp=95, max_hp=100)
            res = cast_spell(Spell.SANCTU, caster=caster, target_member=target)
            assert res.success
            assert res.healed <= 5
            assert target.hp <= 100


def test_sanctum_mani_band_20_to_100():
    """SANCTU_MANI heals randint(0,80)+20 = 20..100, capped at max HP."""
    caster = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, mp=9999, max_mp=9999)
    amounts = []
    with seeded_random_state(13):
        for _ in range(300):
            caster.mp = 9999
            target = Character("Target", "M", Race.HUMAN, Profession.FIGHTER, hp=1, max_hp=200)
            res = cast_spell(Spell.SANCTU_MANI, caster=caster, target_member=target)
            assert res.success
            amounts.append(res.healed)
            assert target.hp == 1 + res.healed
    assert all(20 <= a <= 100 for a in amounts)
    assert min(amounts) == 20
    assert max(amounts) == 100


def test_sanctum_mani_clamped_to_missing_hp():
    """SANCTU_MANI clamps at max HP (missing 10 → at most +10)."""
    caster = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, mp=9999, max_mp=9999)
    with seeded_random_state(17):
        for _ in range(50):
            target = Character("Target", "M", Race.HUMAN, Profession.FIGHTER, hp=90, max_hp=100)
            res = cast_spell(Spell.SANCTU_MANI, caster=caster, target_member=target)
            assert res.success
            assert res.healed <= 10
            assert target.hp <= 100


def test_surmandum_success_good_hp_unchanged(monkeypatch):
    """SURMANDUM 75% success: target GOOD with the HP it had, 0 after a death
    (LW UltimaSpellCombat.c:353, user ruling Q19; GBC's hp=1 and NES's 150
    are outvoted)."""
    import py_exodus.combat.magic as magic

    monkeypatch.setattr(magic.random, "random", lambda: 0.5)
    caster = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, mp=75)
    target = Character("Target", "M", Race.HUMAN, Profession.FIGHTER, hp=0, status=Status.DEAD)
    res = cast_spell(Spell.SURMANDUM, caster=caster, target_member=target)
    assert res.success
    assert target.status == Status.GOOD
    assert target.hp == 0


def test_surmandum_failure_ashes_no_resurrect(monkeypatch):
    """SURMANDUM 25% failure: target becomes ASHES, message fires, no resurrect/heal."""
    import py_exodus.combat.magic as magic

    monkeypatch.setattr(magic.random, "random", lambda: 0.99)
    caster = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, mp=75)
    target = Character("Target", "M", Race.HUMAN, Profession.FIGHTER, hp=0, status=Status.DEAD)
    res = cast_spell(Spell.SURMANDUM, caster=caster, target_member=target)
    assert not res.success
    assert "ashes" in res.message.lower()
    assert target.status == Status.ASHES
    assert target.hp == 0
    assert target.is_disabled()
    assert not target.is_dead()


def test_surmandum_success_rate_seeded():
    """Seeded runs: 75% of SURMANDUM casts succeed."""
    caster = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, mp=9999, max_mp=9999)
    successes = 0
    runs = 400
    with seeded_random_state(23):
        for _ in range(runs):
            caster.mp = 9999
            target = Character("Target", "M", Race.HUMAN, Profession.FIGHTER, hp=0, status=Status.DEAD)
            res = cast_spell(Spell.SURMANDUM, caster=caster, target_member=target)
            if res.success:
                assert target.status == Status.GOOD and target.hp == 0
                successes += 1
            else:
                assert target.status == Status.ASHES
    assert 260 <= successes <= 340  # expected 300 (75%)


def test_ashes_member_save_round_trip(tmp_path):
    """An ASHES roster member round-trips through save_roster/load_roster."""
    from py_exodus.save_system import SaveSystem

    ash = Character("Crumpled", "M", Race.HUMAN, Profession.FIGHTER, hp=0, status=Status.ASHES)
    path = tmp_path / "roster.json"
    SaveSystem.save_roster([ash], path)
    loaded = SaveSystem.load_roster(path)[0]
    # "A" byte round-trips; loaded as the shared-value ASH alias.
    assert loaded.status in (Status.ASHES, Status.ASH)
    assert loaded.status.value == "A"
    assert loaded.is_disabled()
    assert not loaded.is_dead()


# --- Task 17 (GBC parity): NECORP weaken, DECORP kill, ALTAIR 20 rounds -------


def test_necorp_sets_every_living_monster_to_five_hp(asset_mgr, conflict_map):
    """LairWare Necorp (UltimaSpellCombat.c:500-521): every LIVING monster's
    HP becomes exactly 5 and nothing else changes (ledger P-19): it deals no
    damage and kills nothing, so a 40-hp orc and a 2-hp ghoul both end at 5,
    and no debuff is left behind."""
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=999)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=3)
    hps = (40, 2, 100)
    for monster, hp in zip(arena.monsters, hps):
        monster.hp = hp
        monster.max_hp = hp

    res = cast_spell(Spell.NECORP, caster=party.members[0], arena=arena)
    assert res.success
    assert res.damage == 0  # no damage dealt
    assert res.targets_affected == 3
    for monster, hp in zip(arena.monsters, hps):
        assert monster.hp == 5  # exactly 5 — up from 2, down from 40
        assert not monster.is_dead
        assert not hasattr(monster, "weakened")
    assert wiz.exp == 0  # nothing died, no EXP


def test_decorp_lands_a_guaranteed_kill(asset_mgr, conflict_map):
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): on a hit DECORP kills
    the target regardless of hp (GBC battle.c:1285-1296 sets kill=1; LW
    UltimaSpellCombat.c:238,456-472 ports it as damage=255) — not the old
    128-255 damage roll. A miss still misses."""
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=999)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    m = arena.monsters[0]
    px, py = arena.player_positions[0]
    m.x = px
    m.y = py - 1
    m.hp = 200
    m.max_hp = 200

    res = cast_spell(Spell.DECORP, caster=party.members[0], target_dir=Direction.NORTH, arena=arena)
    assert res.success
    assert res.hit
    assert m.is_dead  # killed regardless of the 200 hp
    assert res.targets_affected == 1
