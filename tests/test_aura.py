"""Task 11: aura parity (Java objects/Aura.java + Constants.AuraType) and the
combat aura consumers — NEGATE blocks casting, QUICKNESS skips monster turns,
and the combat N key (Java CombatScreen.negateTime:503-514)."""
import pytest

from py_exodus.assets import AssetManager
from py_exodus.aura import Aura, AuraType
from py_exodus.combat.arena import Action, CombatArena
from py_exodus.combat.magic import NO_TURN_SPELLS, cast_spell
from py_exodus.constants import Profession, Race, Spell, Status
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
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


# --- Java Constants.java:878-886 AuraType ---

def test_aura_types_match_java():
    """AuraType carries every Java enum value, including HORN."""
    assert {t.name for t in AuraType} == {
        "NONE",
        "HORN",
        "JINX",
        "NEGATE",
        "PROTECTION",
        "QUICKNESS",
    }


def test_aura_decrements_to_none():
    aura = Aura()
    aura.set(AuraType.PROTECTION, 2)
    aura.pass_turn()
    assert aura.get_duration() == 1
    assert aura.get_type() == AuraType.PROTECTION
    aura.pass_turn()
    assert aura.get_duration() == 0
    assert aura.get_type() == AuraType.NONE
    assert not aura.is_active()


# --- NEGATE blocks casting (Java SpellUtil.java:73-76) ---

def _negated_cast_setup(asset_mgr, conflict_map):
    party = Party()
    cleric = Character("Cleric", "F", Race.BOBIT, Profession.CLERIC, wisdom=75, mp=50)
    party.add_member(cleric)
    return party, party.members[0]


def test_negate_blocks_casting_without_spending_mana(asset_mgr, conflict_map):
    party, caster = _negated_cast_setup(asset_mgr, conflict_map)
    party.aura.set(AuraType.NEGATE, 3)

    res = cast_spell(Spell.SANCTU, caster=caster, party=party, arena=CombatArena(
        party=party, combat_map=conflict_map, creature_tile="skeleton",
        asset_mgr=asset_mgr, monster_count=1,
    ))

    assert not res.success
    assert res.message == "Spell is negated!"
    assert caster.mp == 50  # Java: adjustMagic runs after the NEGATE check


def test_negated_free_spell_flag_is_consumed_java_order(asset_mgr, conflict_map):
    """Java sets usedFreeSpellInCombat BEFORE the NEGATE check — a negated
    PONTORI burns the free spell but spends no mana (SpellUtil.java:62-76)."""
    party, caster = _negated_cast_setup(asset_mgr, conflict_map)
    arena = CombatArena(party=party, combat_map=conflict_map, creature_tile="skeleton",
                        asset_mgr=asset_mgr, monster_count=1)
    party.aura.set(AuraType.NEGATE, 3)

    res = cast_spell(Spell.PONTORI, caster=caster, party=party, arena=arena)
    assert not res.success
    assert res.message == "Spell is negated!"
    assert caster.mp == 50
    assert caster.used_free_spell_in_combat is True

    # Aura expiry restores casting, but the free spell is gone
    party.aura.set_duration(0)
    res2 = cast_spell(Spell.PONTORI, caster=caster, party=party, arena=arena)
    assert not res2.success
    assert res2.message == "Can't!"
    assert caster.mp == 50


def test_spell_not_negated_with_plain_aura(asset_mgr, conflict_map):
    party, caster = _negated_cast_setup(asset_mgr, conflict_map)
    arena = CombatArena(party=party, combat_map=conflict_map, creature_tile="skeleton",
                        asset_mgr=asset_mgr, monster_count=1)
    party.aura.set(AuraType.QUICKNESS, 3)
    res = cast_spell(Spell.PONTORI, caster=caster, party=party, arena=arena)
    assert res.success


def test_free_spell_check_order(asset_mgr, conflict_map):
    """Java's cast order for the free spells (REPOND/PONTORI, both cost 0):
    mana first, then the free flag, then NEGATE — so the flag-burning-before-NEGATE
    ordering of test_negated_free_spell_flag_is_consumed_java_order is the
    observable slice of that ordering."""
    party = Party()
    caster = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=0)
    party.add_member(caster)
    arena = CombatArena(party=party, combat_map=conflict_map, creature_tile="skeleton",
                        asset_mgr=asset_mgr, monster_count=1)
    res = cast_spell(Spell.REPOND, caster=caster, party=party, arena=arena)
    assert res.success  # cost 0 — the mana check passes even at 0 MP
    assert caster.used_free_spell_in_combat is True


# --- QUICKNESS skips monster turns (Java CombatScreen.finishTurn:481-496) ---

def test_quickness_skips_monster_turns_in_combat(asset_mgr, conflict_map):
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=75)
    party.add_member(wiz)
    arena = CombatArena(party=party, combat_map=conflict_map, creature_tile="orc",
                        asset_mgr=asset_mgr, monster_count=1)

    party.aura.set(AuraType.QUICKNESS, 5)
    positions_before = [(m.x, m.y) for m in arena.monsters]
    hp_before = [m.hp for m in arena.monsters]

    # aura.passTurn runs once per round, then the QUICKNESS check
    for expected in (4, 3, 2, 1):
        results = arena.execute_monster_turns()
        assert results == []
        assert [(m.x, m.y) for m in arena.monsters] == positions_before
        assert [m.hp for m in arena.monsters] == hp_before
        assert party.aura.get_duration() == expected

    # 0 expires the type back to NONE — monsters act again
    arena.execute_monster_turns()
    assert party.aura.get_type() == AuraType.NONE
    assert not party.aura.is_active()


def test_combat_negate_time_key_consumes_powder(asset_mgr, conflict_map, pygame_setup):
    """CombatScreen N: the first member holding powder burns one and sets
    QUICKNESS 6 (Java CombatScreen.negateTime:503-514); with none held it
    logs "None!" and the aura is untouched."""
    from py_exodus.screens.combat_screen import CombatScreen

    m1 = Character("A", "M", Race.HUMAN, Profession.CLERIC, powder=0)
    m2 = Character("B", "M", Race.HUMAN, Profession.CLERIC, powder=3)
    party = Party([PartyMember(m1), PartyMember(m2)])

    screen = CombatScreen(party=party, combat_map=conflict_map,
                          creature_tile="orc", asset_mgr=asset_mgr)
    screen._negate_time()
    assert m1.powder == 0
    assert m2.powder == 2
    assert party.aura.get_type() == AuraType.QUICKNESS
    assert party.aura.get_duration() == 6
    assert any("Stop time with a powder!" in line for line in screen.text_log.lines)

    # Everyone out of powder → "None!", aura expired and untouched
    while party.powder > 0:
        screen._negate_time()
    party.aura.set(AuraType.PROTECTION, 2)
    screen._negate_time()
    assert party.aura.get_type() == AuraType.PROTECTION
    assert party.aura.get_duration() == 2
    assert any("None!" in line for line in screen.text_log.lines)


def test_combat_negate_time_none_message(asset_mgr, conflict_map, pygame_setup):
    from py_exodus.screens.combat_screen import CombatScreen

    party = Party([PartyMember(Character("Solo", "M", Race.HUMAN, Profession.CLERIC, powder=0))])
    screen = CombatScreen(party=party, combat_map=conflict_map,
                          creature_tile="orc", asset_mgr=asset_mgr)
    screen.text_log.add_message("seed")
    screen._negate_time()
    assert any("None!" in line for line in screen.text_log.lines)


# --- ALTAIR sets QUICKNESS 5, PABULUM/ALTAIR do not consume the caster's turn ---

def test_no_turn_spell_set_covers_java_finish_player_turn_gate():
    """LORUM, PABULUM, ALTAIR, DAG_ACRON and the dungeon spells never call
    finishPlayerTurn in Java; the FAL_DIVI/SOMINAE no-ops likewise. The
    combat-castable members are PABULUM and ALTAIR."""
    assert Spell.PABULUM in NO_TURN_SPELLS and Spell.ALTAIR in NO_TURN_SPELLS
    for s in (Spell.LORUM, Spell.DAG_ACRON, Spell.REC_SU, Spell.REC_DU,
              Spell.SUR_ACRON, Spell.DOR_ACRON, Spell.LIB_REC, Spell.SEQUITU,
              Spell.VIEDA, Spell.LUMINAE, Spell.SOMINAE, Spell.FAL_DIVI,
              Spell.FAL_DIVI):
        assert s in NO_TURN_SPELLS


def test_pabulum_does_not_consume_combat_turn(asset_mgr, conflict_map):
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=75)
    party.add_member(wiz)
    arena = CombatArena(party=party, combat_map=conflict_map, creature_tile="orc",
                        asset_mgr=asset_mgr, monster_count=1)
    res = arena.execute_turn(Action.cast(Spell.PABULUM))
    assert res.success
    assert not arena.is_party_round_done
    # The same member acts again — the player round has not advanced
    assert arena.active_party_member_idx == 0


def test_altair_does_not_consume_combat_turn_and_sets_aura(asset_mgr, conflict_map):
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=75)
    party.add_member(wiz)
    arena = CombatArena(party=party, combat_map=conflict_map, creature_tile="orc",
                        asset_mgr=asset_mgr, monster_count=1)
    res = arena.execute_turn(Action.cast(Spell.ALTAIR))
    assert res.success
    assert party.aura.get_type() == AuraType.QUICKNESS
    assert party.aura.get_duration() == 5
    assert arena.active_party_member_idx == 0
    assert not arena.is_party_round_done
