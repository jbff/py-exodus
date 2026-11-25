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
    cleric = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, wisdom=75, mp=50)
    party.add_member(cleric)
    return party, party.members[0]


def test_negate_blocks_casting_without_spending_mana(asset_mgr, conflict_map):
    party, caster = _negated_cast_setup(asset_mgr, conflict_map)
    party.aura.set(AuraType.NEGATE, 3)
    arena = CombatArena(
        party=party, combat_map=conflict_map, creature_tile="skeleton",
        asset_mgr=asset_mgr, monster_count=1,
    )
    mp = caster.mp  # after combatstart's AgeChars (+1, LW UltimaSpellCombat.c:920)

    res = cast_spell(Spell.SANCTU, caster=caster, party=party, arena=arena)

    assert not res.success
    assert res.message == "Spell is negated!"
    assert caster.mp == mp  # Java: adjustMagic runs after the NEGATE check


def test_negated_free_spell_flag_is_consumed_java_order(asset_mgr, conflict_map):
    """Java sets usedFreeSpellInCombat BEFORE the NEGATE check — a negated
    PONTORI burns the free spell but spends no mana (SpellUtil.java:62-76)."""
    party, caster = _negated_cast_setup(asset_mgr, conflict_map)
    arena = CombatArena(party=party, combat_map=conflict_map, creature_tile="skeleton",
                        asset_mgr=asset_mgr, monster_count=1)
    party.aura.set(AuraType.NEGATE, 3)
    mp = caster.mp  # after combatstart's AgeChars (+1, LW UltimaSpellCombat.c:920)

    res = cast_spell(Spell.PONTORI, caster=caster, party=party, arena=arena)
    assert not res.success
    assert res.message == "Spell is negated!"
    assert caster.mp == mp
    assert caster.used_free_spell_in_combat is True

    # Aura expiry restores casting, but the free spell is gone
    party.aura.set_duration(0)
    res2 = cast_spell(Spell.PONTORI, caster=caster, party=party, arena=arena)
    assert not res2.success
    assert res2.message == "Can't!"
    assert caster.mp == mp


def test_spell_not_negated_with_plain_aura(asset_mgr, conflict_map):
    party, caster = _negated_cast_setup(asset_mgr, conflict_map)
    arena = CombatArena(party=party, combat_map=conflict_map, creature_tile="skeleton",
                        asset_mgr=asset_mgr, monster_count=1)
    # Force the latch: this test pins the aura check, not the masskill gate
    arena.masskill = True
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
    arena = CombatArena(party=party, combat_map=conflict_map, creature_tile="orc",
                        asset_mgr=asset_mgr, monster_count=1)
    # Force the latch: this test pins cast ordering, not the masskill gate
    arena.masskill = True
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
    QUICKNESS 10 (GBC battle2.c:722-733 — amended 2026-11-14; LW
    UltimaMain.c:2129-2139); with none held it logs "None!" and the aura is
    untouched."""
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
    assert party.aura.get_duration() == 10
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


# --- ALTAIR sets QUICKNESS 5; ALTAIR and DAG LORUM consume the caster's turn ---

def test_no_turn_spell_set_covers_java_finish_player_turn_gate():
    """LORUM, DAG_ACRON and the dungeon spells never call finishPlayerTurn
    in Java; the SOMINAE no-op likewise. Wizard I is LairWare's DAG LORUM
    (user ruling Q21), an ordinary cast that spends the turn, and so is
    FAL_DIVI (LairWare case 9 casts a cleric spell; ledger P-20)."""
    assert Spell.DAG_LORUM not in NO_TURN_SPELLS
    # LW Altair (UltimaSpellCombat.c:238) spends the caster's turn.
    assert Spell.ALTAIR not in NO_TURN_SPELLS
    assert Spell.FAL_DIVI not in NO_TURN_SPELLS
    for s in (Spell.LORUM, Spell.DAG_ACRON, Spell.REC_SU, Spell.REC_DU,
              Spell.SUR_ACRON, Spell.DOR_ACRON, Spell.LIB_REC, Spell.SEQUITU,
              Spell.VIEDA, Spell.LUMINAE, Spell.SOMINAE):
        assert s in NO_TURN_SPELLS


def test_dag_lorum_consumes_combat_turn(asset_mgr, conflict_map):
    """LW UltimaSpellCombat.c:227-230: Dag Lorum casts anywhere, and in a
    fight it is an ordinary cast that ends the caster's turn."""
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=75)
    party.add_member(wiz)
    party.add_member(Character("Two", "M", Race.HUMAN, Profession.FIGHTER))
    arena = CombatArena(party=party, combat_map=conflict_map, creature_tile="orc",
                        asset_mgr=asset_mgr, monster_count=1)
    res = arena.execute_turn(Action.cast(Spell.DAG_LORUM))
    assert res.success
    assert wiz.mp == 35
    # The turn passed to the next member
    assert arena.active_party_member_idx != 0


def test_altair_consumes_combat_turn_and_sets_aura(asset_mgr, conflict_map):
    """LW UltimaSpellCombat.c:238: Altair sets gTimeNegate = 20 and, like
    every cast, ends the caster's turn; the monster phase that follows is
    the first of the 20 stopped ones (1102-1105)."""
    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=75)
    party.add_member(wiz)
    arena = CombatArena(party=party, combat_map=conflict_map, creature_tile="orc",
                        asset_mgr=asset_mgr, monster_count=1)
    res = arena.execute_turn(Action.cast(Spell.ALTAIR))
    assert res.success
    assert party.aura.get_type() == AuraType.QUICKNESS
    # GBC menucmd.c:1551 — amended 2026-11-14: 20 rounds per LW
    # UltimaSpellCombat.c:238 + NES Bank0F.asm:3329 agreement.
    # The lone caster's turn ended the round; one stopped phase has passed.
    assert party.aura.get_duration() == 19
    assert arena.round_count == 2


# --- Task 17 (GBC parity): stop-time does not work on the EXODUS map ----------

def test_exodus_map_quickness_does_not_skip_monster_turns(asset_mgr, conflict_map, monkeypatch):
    """USER-DIRECTED GBC-RULES DEVIATION (ruled item 16, 2026-11-14, both
    referees): the QUICKNESS (stop-time) aura has NO effect during combat on
    the EXODUS map — the aura's creature-phase skip does not fire and the
    monsters still act (GBC ult3.c:1024-1034; LW UltimaSpellCombat.c:1082,
    1102-1105)."""
    import py_exodus.combat.arena as arena_mod
    from py_exodus.assets import MAP_NAME_TO_ID

    party = Party()
    wiz = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD, intelligence=75, mp=75)
    party.add_member(wiz)
    arena = CombatArena(party=party, combat_map=conflict_map, creature_tile="orc",
                        asset_mgr=asset_mgr, monster_count=1,
                        context_map_id=MAP_NAME_TO_ID["EXODUS"])
    monkeypatch.setattr(arena_mod.random, "randrange", lambda n: 99)  # no teleport/ranged bolt
    monster = arena.monsters[0]
    px, py = arena.player_positions[0]
    monster.x, monster.y = min(px + 3, 10), py
    monster.hp = monster.max_hp = 100

    party.aura.set(AuraType.QUICKNESS, 20)
    arena.execute_monster_turns()
    # The monster advanced (creature phase ran) despite the live aura
    assert monster.x < px + 3
