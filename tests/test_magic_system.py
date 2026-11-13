"""Tests for Ultima III Magic & Spells System."""
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
def asset_mgr():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


@pytest.fixture
def conflict_map(asset_mgr):
    loader = MapLoader(asset_mgr)
    return loader.load_conflict_map("cnflct_a.json")


def test_heal_spell():
    """Step 1 from Task 9 brief: Cleric casting SANCTU."""
    c = Character("Cleric1", "F", Race.BOBIT, Profession.CLERIC)
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
    c = Character("Cleric", "F", Race.BOBIT, Profession.CLERIC)
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
    """SANCTU_MANI (and alias SURMAND) restores character to max HP."""
    c = Character("Cleric", "F", Race.BOBIT, Profession.CLERIC)
    c.mp = 60

    target = Character("Target", "M", Race.HUMAN, Profession.FIGHTER, hp=20, max_hp=150)
    res = cast_spell(Spell.SANCTU_MANI, caster=c, target_member=target)
    assert res.success
    assert target.hp == 150
    assert res.healed == 130


def test_cleric_resurrection():
    """SURMANDUM (and alias ANCRON) resurrects DEAD character to GOOD."""
    c = Character("Cleric", "F", Race.BOBIT, Profession.CLERIC)
    c.mp = 75

    target = Character("Target", "M", Race.HUMAN, Profession.FIGHTER, hp=0, status=Status.DEAD)
    res = cast_spell(Spell.SURMANDUM, caster=c, target_member=target)
    assert res.success
    assert target.status == Status.GOOD
    assert target.hp > 0


def test_cleric_recall_ashes():
    """ANJU_SERMANI recalls ASHES to GOOD and deducts 5 wisdom from caster."""
    c = Character("Cleric", "F", Race.BOBIT, Profession.CLERIC, wisdom=50)
    c.mp = 80

    target = Character("Target", "M", Race.HUMAN, Profession.FIGHTER, hp=0, status=Status.ASHES)
    res = cast_spell(Spell.ANJU_SERMANI, caster=c, target_member=target)
    assert res.success
    assert target.status == Status.GOOD
    assert target.hp > 0
    assert c.wis == 45


def test_wizard_magic_missile_in_combat(asset_mgr, conflict_map):
    """MITTAR deals 16-24 damage along direction to monster."""
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=50, mp=50)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    m = arena.monsters[0]
    # Place monster directly North of player
    px, py = arena.player_positions[0]
    m.x = px
    m.y = py - 2
    initial_hp = m.hp

    res = cast_spell(Spell.MITTAR, caster=party.members[0], target_dir=Direction.NORTH, arena=arena)
    assert res.success
    assert 16 <= res.damage <= 24
    assert m.hp == initial_hp - res.damage


def test_wizard_fireball_in_combat(asset_mgr, conflict_map):
    """FULGAR deals 32-64 damage along direction to monster."""
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
    assert 32 <= res.damage <= 64
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
    """DECORP deals 128-255 damage."""
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=75)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    m = arena.monsters[0]
    px, py = arena.player_positions[0]
    m.x = px
    m.y = py - 1
    m.hp = 200

    res = cast_spell(Spell.DECORP, caster=party.members[0], target_dir=Direction.NORTH, arena=arena)
    assert res.success
    assert 128 <= res.damage <= 255


def test_wizard_stop_time_in_combat(asset_mgr, conflict_map):
    """ALTAIR (ZOMM) sets the QUICKNESS aura for 5 turns (Java
    SpellUtil.java:125-127 — context.getAura().set(AuraType.QUICKNESS, 5))."""
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=75)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=2)
    res = cast_spell(Spell.ALTAIR, caster=party.members[0], arena=arena)
    assert res.success
    assert party.aura.get_type() == AuraType.QUICKNESS
    assert party.aura.get_duration() == 5

    # Monster turns are skipped while the QUICKNESS aura is live
    initial_positions = [(m.x, m.y) for m in arena.monsters]
    results = arena.execute_monster_turns()
    assert len(results) == 0
    assert [(m.x, m.y) for m in arena.monsters] == initial_positions


def test_repond_against_orcs_free_spell(asset_mgr, conflict_map, monkeypatch):
    """REPOND destroys only tile=="orc" creatures and is limited to once per
    combat (Java SpellUtil.spellRepond:462 — "orc".equals(cr.getTile()))."""
    import py_exodus.combat.magic as magic

    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=50, mp=50)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=3)
    # Pin the turn rolls above every threshold (60 >= 50/35/20)
    monkeypatch.setattr(magic.random, "randrange", lambda n: 60)
    res = cast_spell(Spell.REPOND, caster=party.members[0], arena=arena)
    assert res.success
    assert all(m.is_dead for m in arena.monsters)

    # Second attempt fails (free spell used once per combat)
    res2 = cast_spell(Spell.REPOND, caster=party.members[0], arena=arena)
    assert not res2.success
    assert "can't" in res2.message.lower()


def test_repond_spares_non_orc_goblinoids(asset_mgr, conflict_map, monkeypatch):
    """Java's goblinoid set is the single tile "orc" — gremlins/trolls/goblins
    are spared (SpellUtil.spellRepond:462)."""
    import py_exodus.combat.magic as magic
    from py_exodus.entities.defs import CreatureDef

    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=50, mp=50)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=2)
    for m in arena.monsters:
        m.tile = "troll"
        m.definition = CreatureDef(id=2, name="Troll", tile="troll", basehp=48, hp=48, exp=5, undead=False)
    monkeypatch.setattr(magic.random, "randrange", lambda n: 60)
    res = cast_spell(Spell.REPOND, caster=party.members[0], arena=arena)
    assert res.success
    assert all(not m.is_dead for m in arena.monsters)


def test_pontori_against_undead(asset_mgr, conflict_map, monkeypatch):
    """PONTORI turns and destroys undead monsters; only the undead —
    not orc tiles — are eligible (SpellUtil.spellUndead:409)."""
    import py_exodus.combat.magic as magic

    party = Party()
    cleric = Character("Cleric", "F", Race.BOBIT, Profession.CLERIC, wisdom=50, mp=50, level=20)
    party.add_member(cleric)

    arena = CombatArena(party, conflict_map, creature_tile="skeleton", asset_mgr=asset_mgr, monster_count=2)
    res = cast_spell(Spell.PONTORI, caster=party.members[0], arena=arena)
    assert res.success
    assert all(m.is_dead for m in arena.monsters)
    assert cleric.exp > 0  # XP is awarded along the damage path


def test_pontori_requires_turn_roll_at_low_level(asset_mgr, conflict_map, monkeypatch):
    """Below level 5 the per-creature roll is rand(100) >= 50 (50% chance)."""
    import py_exodus.combat.magic as magic

    party = Party()
    cleric = Character("Cleric", "F", Race.BOBIT, Profession.CLERIC, wisdom=50, mp=50)
    party.add_member(cleric)  # level 1

    arena = CombatArena(party, conflict_map, creature_tile="skeleton", asset_mgr=asset_mgr, monster_count=2)

    # Roll 10 < 50 — no creature turns
    monkeypatch.setattr(magic.random, "randrange", lambda *a, **k: 10)
    res = cast_spell(Spell.PONTORI, caster=party.members[0], arena=arena)
    assert res.success
    assert all(not m.is_dead for m in arena.monsters)

    caster = party.members[0]
    caster.used_free_spell_in_combat = False
    if hasattr(cleric, "used_free_spell_in_combat"):
        cleric.used_free_spell_in_combat = False
    caster.mp = 50
    monkeypatch.setattr(magic.random, "randrange", lambda *a, **k: 90)
    res2 = cast_spell(Spell.PONTORI, caster=party.members[0], arena=arena)
    assert res2.success
    assert all(m.is_dead for m in arena.monsters)


def test_area_mass_blast_spells(asset_mgr, conflict_map):
    """NOXUM and UNSPEAKABLE damage all monsters in arena."""
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=90)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=4)
    for m in arena.monsters:
        m.hp = 100
        m.max_hp = 100

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
    PABULUM feeds 5-9 per member (Utils.getRandomBetween(5,10) == 5..9), and
    the dungeon spells are Dungeon-state operations — party fields are never
    mutated outside a dungeon (old torch_duration / dungeon_level writes are
    gone)."""
    party = Party()
    cleric = Character("Cleric", "F", Race.BOBIT, Profession.CLERIC, wisdom=75, mp=80, food=10)
    wizard = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=80, food=10)
    party.add_member(cleric)
    party.add_member(wizard)

    # Light spell (Cleric LUMINAE) — torch boolean, no duration arithmetic
    res_light = cast_spell(Spell.LUMINAE, caster=party.members[0], party=party)
    assert res_light.success
    assert not hasattr(party, "torch_duration") or party.torch_duration == 0

    # Food spell (Wizard PABULUM): 5-9 food per member
    res_food = cast_spell(Spell.PABULUM, caster=party.members[1], party=party)
    assert res_food.success
    assert 15 <= cleric.food <= 19
    assert 15 <= wizard.food <= 19

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
    assert "empty space" in res.message.lower()


def test_incapacitated_caster_cannot_cast():
    """Dead or ashes caster cannot cast."""
    dead_wiz = Character("DeadWiz", "M", Race.FUZZY, Profession.WIZARD, status=Status.DEAD, mp=50)
    res = cast_spell(Spell.FULGAR, caster=dead_wiz, target_dir=Direction.NORTH)
    assert not res.success
    assert "cannot cast" in res.message.lower()


def test_targeted_spells_validation_failures():
    """Restorative and life spells validate target condition before MP spend."""
    cleric = Character("Cleric", "F", Race.BOBIT, Profession.CLERIC, wisdom=50, mp=90)
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
    druid = Character("Druid", "M", Race.BOBIT, Profession.DRUID, wisdom=40, intelligence=40, mp=40)
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
    cleric = Character("Cleric", "F", Race.BOBIT, Profession.CLERIC, wisdom=75, mp=75)
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
    c = Character("Cleric", "F", Race.BOBIT, Profession.CLERIC, wisdom=50, mp=50)
    res = cast_spell("NOT_A_REAL_SPELL", caster=c)
    assert not res.success
    assert "unknown spell" in res.message.lower()


def test_spell_letter_code_resolution_by_discipline(asset_mgr, conflict_map):
    """Cleric casting 'A' resolves to PONTORI, Wizard to REPOND, Druid by chosen discipline."""
    from py_exodus.combat.magic import get_castable_spell_types, resolve_spell

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
    cleric_char = Character("Cleric", "F", Race.BOBIT, Profession.CLERIC, wisdom=50, mp=50)
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
    cleric = Character("Cleric", "F", Race.BOBIT, Profession.CLERIC, wisdom=50, mp=50, hp=100, max_hp=100)
    fighter = Character("Fighter", "M", Race.HUMAN, Profession.FIGHTER, strength=50, hp=30, max_hp=100)
    druid = Character("Druid", "M", Race.BOBIT, Profession.DRUID, wisdom=50, intelligence=50, mp=50)
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

    # User inputs 'C' for Sanctu
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


def test_appar_unem_disarms_and_gets_chest():
    """Verify APPAR_UNEM safely opens, gets gold, and removes chest without requiring 'G'."""
    party = Party(x=10, y=10, gold=100)
    cleric = Character("Bishop", "M", Race.BOBIT, Profession.CLERIC, wisdom=50, mp=50)
    party.add_member(cleric)

    # Place a chest at the party's own tile (Java getChest scans exactly cx == x && cy == y)
    party.dynamic_objects.append({"tile": "chest", "x": 10, "y": 10})
    assert len(party.dynamic_objects) == 1

    # Cast APPAR_UNEM (direction prompted then ignored by Java)
    res = cast_spell(Spell.APPAR_UNEM, caster=cleric, party=party, target_dir=Direction.SOUTH)
    assert res.success is True
    assert "The Chest Holds" in res.message
    assert party.gold > 100
    assert len(party.dynamic_objects) == 0

    # Cast again when no chest is nearby
    res2 = cast_spell(Spell.APPAR_UNEM, caster=cleric, party=party, target_dir=Direction.NORTH)
    assert res2.success is False
    assert "Not Here!" in res2.message


def test_appar_unem_prompt_flow_never_asks_direction():
    """USER RULING 2026-11-11: APPAR_UNEM gets no direction prompt. Java asks
    "Direction?" then ignores the answer (SpellInputProcessor.java:52-61) —
    the ruling removes the prompt, so selecting the spell dispatches straight
    to the caster's-tile chest effect (SpellUtil.java:140-148)."""
    from py_exodus.combat.magic import prompt_cast_party
    from py_exodus.ui.text_log import TextLog

    party = Party(x=10, y=10, gold=100)
    cleric = Character("Bishop", "M", Race.BOBIT, Profession.CLERIC, wisdom=50, mp=50)
    party.add_member(cleric)
    party.dynamic_objects.append({"tile": "chest", "x": 10, "y": 10})

    log = TextLog()
    prompt_cast_party(log, party)
    log.handle_char("1")  # member 1
    log.handle_char("B")  # APPAR_UNEM

    # The flow completed without any further prompt — no Direction? step.
    assert not log.is_waiting_for_input
    all_log = "\n".join(str(line) for line in log.history)
    assert "Direction?" not in all_log
    assert "The Chest Holds" in all_log
    assert party.gold > 100
    assert len(party.dynamic_objects) == 0


# --- Task 11: exact Java spell-table rows (audit Part 1) ---

def test_sanctu_heals_java_range():
    """Java Party.java:417 heal: health += 75 + (rand.nextInt(256) % 25);
    capped at max health (Party.java:432-435)."""
    import py_exodus.combat.magic as magic

    c = Character("Cleric1", "F", Race.BOBIT, Profession.CLERIC, mp=20, hp=50, max_hp=200)
    res = cast_spell(Spell.SANCTU, caster=c, party=None, target_member=c)
    assert res.success
    assert 125 <= c.hp <= 149  # 50 + 75..99

    c2 = Character("Cleric2", "F", Race.BOBIT, Profession.CLERIC, mp=20, hp=50, max_hp=200)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(magic.random, "randrange", lambda *a, **k: 255)
        cast_spell(Spell.SANCTU, caster=c2, party=None, target_member=c2)
        assert c2.hp == 130  # 50 + 75 + (255 % 25)

    # Capped at max health
    c3 = Character("Cleric3", "F", Race.BOBIT, Profession.CLERIC, mp=20, hp=80, max_hp=100)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(magic.random, "randrange", lambda *a, **k: 0)
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


def test_mentar_rolls_32_to_intell_inclusive(asset_mgr, conflict_map, monkeypatch):
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
    assert res.damage == 34


def test_noxum_group_uses_get_random_between(asset_mgr, conflict_map, monkeypatch):
    """spellGroupDamage rolls Utils.getRandomBetween(min, max) — exclusive of
    max (Utils.java:50-52); the max(24, int) floor is gone (NOXUM 24/int)."""
    import py_exodus.combat.magic as magic

    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=75)
    party.add_member(wiz)
    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=2)
    for m in arena.monsters:
        m.hp = 100
        m.max_hp = 100

    calls = {"n": 0}

    def fake_randrange(*a, **k):
        if a and a[0] == 51:  # getRandomBetween(24, 75) → randrange(51)
            calls["n"] += 1
            return 50  # → damage 24 + 50 = 74
        return 0

    monkeypatch.setattr(magic.random, "randrange", fake_randrange)
    res = cast_spell(Spell.NOXUM, caster=party.members[0], arena=arena)
    assert res.success
    assert calls["n"] == 2  # one roll per creature
    for m in arena.monsters:
        assert m.hp == 100 - 74


def test_zxkuqyb_ports_java_bug(asset_mgr, conflict_map, monkeypatch):
    """useMaskOfMinax (SpellUtil.java:646-688): rand(3)==0 → 255; otherwise
    hp <= 23 → 15; hp > 23 → hp * (3/4) — and Java's integer 3/4 is 0, so
    the damage is 0. The max(15, hp*3//4) invention is gone."""
    import py_exodus.combat.magic as magic

    party = Party()
    cleric = Character("Cleric", "F", Race.BOBIT, Profession.CLERIC, wisdom=75, mp=75)
    party.add_member(cleric)

    # randrange always 0 → the 1/3 roll of 255 fires for everyone
    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    m = arena.monsters[0]
    m.hp = 100
    m.max_hp = 100
    monkeypatch.setattr(magic.random, "randrange", lambda *a, **k: 0)
    cast_spell(Spell.ZXKUQYB, caster=party.members[0], arena=arena)
    assert m.is_dead  # 255 damage

    # randrange nonzero → survivors take 0 (hp > 23) or 15 (hp <= 23)
    cleric.mp = 75
    arena2 = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=2)
    arena2.monsters[0].hp = 100
    arena2.monsters[0].max_hp = 100
    arena2.monsters[1].hp = 20
    arena2.monsters[1].max_hp = 100
    monkeypatch.setattr(magic.random, "randrange", lambda *a, **k: 1)
    res2 = cast_spell(Spell.ZXKUQYB, caster=party.members[0], arena=arena2)
    assert res2.success
    assert arena2.monsters[0].hp == 100  # hp * (3//4) == 0
    assert arena2.monsters[1].hp == 5    # 15 damage


def test_unspeakable_java_dice(asset_mgr, conflict_map, monkeypatch):
    """useRageOfGod (SpellUtil.java:690-732): rand(2)==0 → 255; elif rand(2)==0
    → hp - 23 (0 if hp <= 23); else hp / 2. No max(15, ...) floor."""
    import py_exodus.combat.magic as magic

    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=75)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    m = arena.monsters[0]
    m.hp = 100
    m.max_hp = 100
    monkeypatch.setattr(magic.random, "randrange", lambda *a, **k: 0)
    cast_spell(Spell.UNSPEAKABLE, caster=party.members[0], arena=arena)
    assert m.is_dead  # rand(2)==0 → 255

    # second branch: rand 1 then 0 → hp - 23
    wiz.mp = 75
    arena2 = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    m2 = arena2.monsters[0]
    m2.hp = 100
    m2.max_hp = 100
    seq = [1, 0]
    monkeypatch.setattr(magic.random, "randrange", lambda *a, **k: seq.pop(0))
    cast_spell(Spell.UNSPEAKABLE, caster=party.members[0], arena=arena2)
    assert m2.hp == 23  # 100 - (hp - 23) dealt 77 damage

    # otherwise branch: rand 1 forever → hp / 2
    wiz.mp = 75
    arena3 = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    m3 = arena3.monsters[0]
    m3.hp = 99
    m3.max_hp = 99
    monkeypatch.setattr(magic.random, "randrange", lambda *a, **k: 1)
    cast_spell(Spell.UNSPEAKABLE, caster=party.members[0], arena=arena3)
    assert m3.hp == 50  # 99 // 2 == 49 damage


def test_pabulum_food_deterministic(monkeypatch):
    """PABULUM feeds Utils.getRandomBetween(5,10) == 5..9 per member
    (SpellUtil.java:111-114)."""
    import py_exodus.combat.magic as magic

    party = Party()
    c1 = Character("A", "F", Race.BOBIT, Profession.WIZARD, mp=50, food=0)
    c2 = Character("B", "M", Race.HUMAN, Profession.WIZARD, mp=50, food=0)
    party.add_member(c1)
    party.add_member(c2)

    rolls = [0, 4]  # member 1 rolls 0 → 5 food, member 2 rolls 4 → 9 food

    def fake_randrange(*a, **k):
        if a and a[0] == 5:
            return rolls.pop(0) if rolls else 0
        return 0

    monkeypatch.setattr(magic.random, "randrange", fake_randrange)
    res = cast_spell(Spell.PABULUM, caster=party.members[0], party=party)
    assert res.success
    assert c1.food == 5
    assert c2.food == 9


def test_fulgar_resisted_by_fire_resists(asset_mgr, conflict_map):
    """castAt (Utils.java:815-820): FULGAR against a creature with
    resists == "fire" logs "Resisted!" and deals no damage."""
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
    assert res.damage == 0
    assert "Resisted!" in res.message
    assert arena.monsters[0].hp == 100


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


def test_dag_acron_blinks_on_the_world_map(monkeypatch):
    """Java spellBlink (SpellUtil.java:267-350): a random valid direction,
    the 0x10-grid distance walk, then a backward scan to the nearest walkable
    tile; casting is surface-only."""
    import py_exodus.combat.magic as magic
    from py_exodus.assets import TileDef
    from py_exodus.world.map import ConflictMap

    world = ConflictMap(map_type=MapType.WORLD, width=64, height=64)
    world.tiles = [TileDef(index=3, name="floor") for _ in range(64 * 64)]

    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=50, mp=50)
    party.add_member(wiz)
    party.x = 8
    party.y = 1

    monkeypatch.setattr(pyrandom, "choice", lambda seq: Direction.EAST)
    monkeypatch.setattr(magic.random, "choice", lambda seq: Direction.EAST)
    # Pin the 16-step extension roll low: rand.nextInt(diff*diff) <= distance
    monkeypatch.setattr(magic.random, "randrange", lambda *a, **k: 0)

    res = cast_spell(Spell.DAG_ACRON, caster=party.members[0], party=party, world_map=world)
    assert res.success
    # EAST from x=8: distance = x % 0x10 = 8 → 0x10 - 8 = 8 → walks to (16, 1)
    assert (party.x, party.y) == (16, 1)


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


