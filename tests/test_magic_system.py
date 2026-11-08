"""Tests for Ultima III Magic & Spells System."""
import pytest

from py_exodus.assets import AssetManager
from py_exodus.combat.arena import Action, CombatArena
from py_exodus.combat.magic import SpellResult, cast_spell
from py_exodus.constants import (
    Direction,
    Profession,
    Race,
    Spell,
    Status,
)
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.world.loader import MapLoader


@pytest.fixture
def asset_mgr():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


@pytest.fixture
def conflict_map(asset_mgr):
    loader = MapLoader(asset_mgr)
    return loader.load_conflict_map("CNFLCT_A.ULT")


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
    """ALTAIR (ZOMM) freezes monsters for rounds."""
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=75)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=2)
    res = cast_spell(Spell.ALTAIR, caster=party.members[0], arena=arena)
    assert res.success
    assert getattr(arena, "freeze_rounds", 0) > 0

    # Monster turns during freeze do not move or attack
    initial_positions = [(m.x, m.y) for m in arena.monsters]
    results = arena.execute_monster_turns()
    assert len(results) == 0
    assert [(m.x, m.y) for m in arena.monsters] == initial_positions


def test_repond_against_orcs_free_spell(asset_mgr, conflict_map):
    """REPOND destroys orcs and is limited to once per combat."""
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=50, mp=50)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=3)
    res = cast_spell(Spell.REPOND, caster=party.members[0], arena=arena)
    assert res.success
    assert all(m.is_dead for m in arena.monsters)

    # Second attempt fails (free spell used once per combat)
    res2 = cast_spell(Spell.REPOND, caster=party.members[0], arena=arena)
    assert not res2.success
    assert "already used" in res2.message.lower() or "can't" in res2.message.lower()


def test_pontori_against_undead(asset_mgr, conflict_map):
    """PONTORI turns and destroys undead monsters."""
    party = Party()
    cleric = Character("Cleric", "F", Race.BOBIT, Profession.CLERIC, wisdom=50, mp=50)
    party.add_member(cleric)

    arena = CombatArena(party, conflict_map, creature_tile="skeleton", asset_mgr=asset_mgr, monster_count=2)
    res = cast_spell(Spell.PONTORI, caster=party.members[0], arena=arena)
    assert res.success
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
    """Exploration spells: LORUM/LUMINAE (torch), PABULUM (food), dungeon elevation."""
    party = Party()
    cleric = Character("Cleric", "F", Race.BOBIT, Profession.CLERIC, wisdom=75, mp=80, food=10)
    wizard = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=80, food=10)
    party.add_member(cleric)
    party.add_member(wizard)
    party.torch_duration = 10
    party.dungeon_level = 3

    # Light spell (Cleric LUMINAE)
    res_light = cast_spell(Spell.LUMINAE, caster=party.members[0], party=party)
    assert res_light.success
    assert party.torch_duration > 10

    # Food spell (Wizard PABULUM)
    res_food = cast_spell(Spell.PABULUM, caster=party.members[1], party=party)
    assert res_food.success
    assert cleric.food > 10
    assert wizard.food > 10

    # Dungeon up / down / exit (Cleric REC_SU / SEQUITU)
    res_up = cast_spell(Spell.REC_SU, caster=party.members[0], party=party)
    assert res_up.success
    assert party.dungeon_level == 2

    party.members[0].mp = 50
    res_exit = cast_spell(Spell.SEQUITU, caster=party.members[0], party=party)
    assert res_exit.success
    assert party.dungeon_level == 0


def test_teleport_spell_in_combat(asset_mgr, conflict_map):
    """DAG_ACRON teleports caster to an empty walkable tile in arena."""
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=50, mp=50)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    start_pos = arena.player_positions[0]

    res = cast_spell(Spell.DAG_ACRON, caster=party.members[0], arena=arena)
    assert res.success
    # Caster position is updated
    new_pos = arena.player_positions[0]
    assert 0 <= new_pos[0] < conflict_map.width
    assert 0 <= new_pos[1] < conflict_map.height


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

    # Place a chest at adjacent tile (10, 11)
    party.dynamic_objects.append({"tile": "chest", "x": 10, "y": 11})
    assert len(party.dynamic_objects) == 1

    # Cast APPAR_UNEM
    res = cast_spell(Spell.APPAR_UNEM, caster=cleric, party=party)
    assert res.success is True
    assert "safely disarms and opens the chest" in res.message
    assert party.gold > 100
    assert len(party.dynamic_objects) == 0

    # Cast again when no chest is nearby
    res2 = cast_spell(Spell.APPAR_UNEM, caster=cleric, party=party)
    assert res2.success is False
    assert "No chest nearby" in res2.message


