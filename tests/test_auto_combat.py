"""Tests for Auto-Combat AI and CombatScreen integration."""
from types import SimpleNamespace

import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.aura import AuraType
from py_exodus.combat.arena import ActionType, CombatArena
from py_exodus.combat.auto_combat import choose_auto_combat_action
from py_exodus.constants import Direction, Profession, Race, Spell, Status, TileAttrib, WeaponType
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.screens.combat_screen import CombatScreen
from py_exodus.world.loader import MapLoader
from py_exodus.world.map import ConflictMap


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


def _open_arena(
    weapon: WeaponType = WeaponType.SWORD,
    hp: int = 100,
    max_hp: int = 100,
    asset_mgr: AssetManager | None = None,
    monster_count: int = 1,
) -> CombatArena:
    party = Party()
    hero = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, strength=50, dexterity=50)
    hero.weapon = weapon
    hero.hp = hp
    hero.max_hp = max_hp
    party.add_member(hero)

    cmap = ConflictMap(width=11, height=11, tiles=[None] * (11 * 11))
    arena = CombatArena(
        party=party,
        combat_map=cmap,
        creature_tile="orc",
        asset_mgr=asset_mgr,
        monster_count=monster_count,
    )
    arena.player_positions[0] = (5, 5)
    return arena


def test_pass_when_no_visible_monsters():
    arena = _open_arena(monster_count=1)
    arena.monsters[0].visible = False
    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.PASS

    arena.monsters[0].visible = True
    arena.monsters[0].hp = 0
    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.PASS


def test_adjacent_melee_attack(asset_mgr):
    arena = _open_arena(weapon=WeaponType.SWORD, asset_mgr=asset_mgr, monster_count=1)
    arena.monsters[0].x = 5
    arena.monsters[0].y = 4
    action = choose_auto_combat_action(arena, 0, asset_mgr=asset_mgr)
    assert action.type == ActionType.ATTACK
    assert action.direction == Direction.NORTH


def test_ranged_attack_clear_los_with_asset_mgr(asset_mgr):
    arena = _open_arena(weapon=WeaponType.BOW, asset_mgr=asset_mgr, monster_count=1)
    arena.monsters[0].x = 8
    arena.monsters[0].y = 5
    action = choose_auto_combat_action(arena, 0, asset_mgr=asset_mgr)
    assert action.type == ActionType.ATTACK
    assert action.direction == Direction.EAST


def test_ranged_attack_clear_los_without_asset_mgr_fallback():
    arena = _open_arena(weapon=WeaponType.SLING, asset_mgr=None, monster_count=1)
    arena.monsters[0].x = 5
    arena.monsters[0].y = 2
    action = choose_auto_combat_action(arena, 0, asset_mgr=None)
    assert action.type == ActionType.ATTACK
    assert action.direction == Direction.NORTH


def test_ranged_attack_blocked_by_wall_does_not_fire(asset_mgr):
    arena = _open_arena(weapon=WeaponType.BOW, asset_mgr=asset_mgr, monster_count=1)
    arena.monsters[0].x = 5
    arena.monsters[0].y = 2
    wall = SimpleNamespace(attribs=TileAttrib.UNWALKABLE)
    arena.combat_map.set_tile(5, 4, wall)

    action = choose_auto_combat_action(arena, 0, asset_mgr=asset_mgr)
    assert not (action.type == ActionType.ATTACK and action.direction == Direction.NORTH)


def test_advance_toward_nearest_enemy(asset_mgr):
    arena = _open_arena(weapon=WeaponType.SWORD, asset_mgr=asset_mgr, monster_count=2)
    arena.player_positions[0] = (5, 8)
    arena.monsters[0].x = 5
    arena.monsters[0].y = 3
    arena.monsters[1].x = 9
    arena.monsters[1].y = 9
    # (9, 9) is closer in Manhattan distance (4+1=5) than (5, 3) (0+5=5)?
    # Make monster 1 clearly farther:
    arena.monsters[1].x = 10
    arena.monsters[1].y = 10

    action = choose_auto_combat_action(arena, 0, asset_mgr=asset_mgr)
    assert action.type == ActionType.MOVE
    assert action.direction == Direction.NORTH


def test_advance_ranged_prefers_cardinal_alignment(asset_mgr):
    arena = _open_arena(weapon=WeaponType.BOW, asset_mgr=asset_mgr, monster_count=1)
    arena.player_positions[0] = (5, 8)
    arena.monsters[0].x = 3
    arena.monsters[0].y = 5

    action = choose_auto_combat_action(arena, 0, asset_mgr=asset_mgr)
    assert action.type == ActionType.MOVE
    assert action.direction == Direction.WEST


def test_low_hp_retreat_when_adjacent_enemy(asset_mgr):
    arena = _open_arena(
        weapon=WeaponType.SWORD, hp=10, max_hp=100, asset_mgr=asset_mgr, monster_count=1
    )
    arena.player_positions[0] = (5, 5)
    arena.monsters[0].x = 5
    arena.monsters[0].y = 4

    action = choose_auto_combat_action(arena, 0, asset_mgr=asset_mgr)
    assert action.type == ActionType.MOVE
    assert action.direction == Direction.SOUTH


def test_combat_screen_toggle_tab_f2_and_escape(asset_mgr, conflict_map):
    party = Party()
    hero = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, strength=50, dexterity=50)
    party.add_member(hero)

    combat = CombatScreen(
        party=party,
        combat_map=conflict_map,
        creature_tile="orc",
        asset_mgr=asset_mgr,
        monster_count=1,
    )
    assert combat.auto_combat is False

    # K_TAB turns auto_combat ON
    combat.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB))
    assert combat.auto_combat is True
    assert "Auto-combat ON." in combat.text_log.lines[-1]

    # K_F2 turns auto_combat OFF
    combat.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F2))
    assert combat.auto_combat is False
    assert "Auto-combat OFF." in combat.text_log.lines[-1]

    # K_TAB ON, then K_ESCAPE turns OFF
    combat.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB))
    assert combat.auto_combat is True
    combat.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    assert combat.auto_combat is False
    assert "Auto-combat OFF." in combat.text_log.lines[-1]


def test_combat_screen_auto_combat_full_battle_to_victory(asset_mgr, conflict_map):
    party = Party()
    for i in range(2):
        hero = Character(
            f"Hero{i}", "M", Race.HUMAN, Profession.FIGHTER, strength=99, dexterity=99
        )
        hero.weapon = WeaponType.SWORD_P4
        hero.hp = 200
        hero.max_hp = 200
        party.add_member(hero)

    combat = CombatScreen(
        party=party,
        combat_map=conflict_map,
        creature_tile="orc",
        asset_mgr=asset_mgr,
        monster_count=2,
    )
    for m in combat.arena.monsters:
        m.hp = 10

    combat.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB))
    assert combat.auto_combat is True

    for _ in range(200):
        if combat.arena.is_finished:
            break
        combat.update(0.20)

    assert combat.arena.is_finished is True
    assert combat.arena.is_victory is True


def _caster_arena(
    profession: Profession,
    mp: int = 50,
    weapon: WeaponType = WeaponType.DAGGER,
    creature_tile: str = "orc",
    monster_count: int = 1,
    asset_mgr: AssetManager | None = None,
) -> CombatArena:
    party = Party()
    caster = Character("Caster", "M", Race.HUMAN, profession, intelligence=50, wisdom=50)
    caster.weapon = weapon
    caster.hp = 100
    caster.max_hp = 100
    caster.mp = mp
    party.add_member(caster)

    cmap = ConflictMap(width=11, height=11, tiles=[None] * (11 * 11))
    arena = CombatArena(
        party=party,
        combat_map=cmap,
        creature_tile=creature_tile,
        asset_mgr=asset_mgr,
        monster_count=monster_count,
    )
    arena.player_positions[0] = (5, 5)
    return arena


def test_wizard_casts_repond_against_orcs_and_respects_free_flag_and_negate():
    arena = _caster_arena(Profession.WIZARD, mp=0, creature_tile="orc", monster_count=1)
    arena.monsters[0].x = 5
    arena.monsters[0].y = 2

    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.CAST
    assert action.spell == Spell.REPOND

    # Already used free spell in combat -> does not cast REPOND
    arena.party.members[0].used_free_spell_in_combat = True
    action = choose_auto_combat_action(arena, 0)
    assert action.spell != Spell.REPOND

    # Reset free flag, activate NEGATE aura -> does not cast any spell
    arena.party.members[0].used_free_spell_in_combat = False
    arena.party.aura.set(AuraType.NEGATE, 5)
    action = choose_auto_combat_action(arena, 0)
    assert action.type != ActionType.CAST


def test_cleric_casts_pontori_against_skeletons():
    arena = _caster_arena(Profession.CLERIC, mp=0, creature_tile="skeleton", monster_count=1)
    arena.monsters[0].x = 5
    arena.monsters[0].y = 2

    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.CAST
    assert action.spell == Spell.PONTORI

    arena.party.members[0].used_free_spell_in_combat = True
    action = choose_auto_combat_action(arena, 0)
    assert action.spell != Spell.PONTORI


def test_cleric_heals_lowest_hp_living_ally_with_sanctu_and_sanctu_mani():
    arena = _caster_arena(Profession.CLERIC, mp=20, creature_tile="orc", monster_count=1)
    arena.monsters[0].x = 9
    arena.monsters[0].y = 9

    dead_ally = Character("Dead", "M", Race.HUMAN, Profession.FIGHTER)
    dead_ally.hp = 0
    dead_ally.max_hp = 100
    dead_ally.status = Status.DEAD

    hurt_ally = Character("Hurt", "M", Race.HUMAN, Profession.FIGHTER)
    hurt_ally.hp = 30
    hurt_ally.max_hp = 100

    critical_ally = Character("Crit", "M", Race.HUMAN, Profession.FIGHTER)
    critical_ally.hp = 15
    critical_ally.max_hp = 100

    arena.party.add_member(dead_ally)
    arena.party.add_member(hurt_ally)
    arena.party.add_member(critical_ally)

    # With 20 MP (< 50), Cleric casts SANCTU on lowest-HP living ally
    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.CAST
    assert action.spell == Spell.SANCTU
    assert action.target_member is arena.party.members[3]

    # With >= 50 MP, Cleric upgrades to SANCTU_MANI
    arena.party.members[0].mp = 50
    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.CAST
    assert action.spell == Spell.SANCTU_MANI
    assert action.target_member is arena.party.members[3]


def test_wizard_casts_mittar_when_lined_up_and_skips_with_strong_weapons(asset_mgr):
    arena = _caster_arena(
        Profession.WIZARD,
        mp=10,
        weapon=WeaponType.DAGGER,
        creature_tile="orc",
        monster_count=1,
        asset_mgr=asset_mgr,
    )
    arena.party.members[0].used_free_spell_in_combat = True
    arena.monsters[0].x = 5
    arena.monsters[0].y = 1  # Distance 4 (within range 5)

    action = choose_auto_combat_action(arena, 0, asset_mgr=asset_mgr)
    assert action.type == ActionType.CAST
    assert action.spell == Spell.MITTAR
    assert action.direction == Direction.NORTH

    # Wielding BOW_P2 or EXOTIC skips MITTAR
    for w in (WeaponType.BOW_P2, WeaponType.EXOTIC):
        arena.party.members[0].weapon = w
        action = choose_auto_combat_action(arena, 0, asset_mgr=asset_mgr)
        assert action.spell != Spell.MITTAR


def test_wizard_advances_to_cardinal_alignment_when_can_cast_mittar():
    arena = _caster_arena(
        Profession.WIZARD, mp=10, weapon=WeaponType.DAGGER, creature_tile="orc", monster_count=1
    )
    arena.party.members[0].used_free_spell_in_combat = True
    arena.player_positions[0] = (5, 8)
    arena.monsters[0].x = 3
    arena.monsters[0].y = 5

    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.MOVE
    assert action.direction == Direction.WEST


def test_high_threat_masskill_unspeakable_and_zxkuqyb():
    # Wizard: UNSPEAKABLE when >= 2 monsters and threat > 60
    wiz_arena = _caster_arena(
        Profession.WIZARD, mp=80, creature_tile="orc", monster_count=2
    )
    wiz_arena.party.members[0].used_free_spell_in_combat = True
    wiz_arena.monsters[0].x = 1
    wiz_arena.monsters[0].y = 1
    wiz_arena.monsters[0].exp = 35
    wiz_arena.monsters[1].x = 9
    wiz_arena.monsters[1].y = 9
    wiz_arena.monsters[1].exp = 35  # total threat = 70 > 60

    action = choose_auto_combat_action(wiz_arena, 0)
    assert action.type == ActionType.CAST
    assert action.spell == Spell.UNSPEAKABLE

    # Cleric: ZXKUQYB when >= 2 monsters and threat > 80 (poisonous doubles exp)
    cleric_arena = _caster_arena(
        Profession.CLERIC, mp=80, creature_tile="orc", monster_count=2
    )
    cleric_arena.monsters[0].x = 1
    cleric_arena.monsters[0].y = 1
    cleric_arena.monsters[0].exp = 25
    cleric_arena.monsters[0].poisons = True  # 50 threat
    cleric_arena.monsters[1].x = 9
    cleric_arena.monsters[1].y = 9
    cleric_arena.monsters[1].exp = 35  # total threat = 85 > 80

    action = choose_auto_combat_action(cleric_arena, 0)
    assert action.type == ActionType.CAST
    assert action.spell == Spell.ZXKUQYB

    # Only 1 monster -> does not cast masskill even with high exp
    cleric_arena.monsters[1].hp = 0
    cleric_arena.monsters[0].exp = 100
    action = choose_auto_combat_action(cleric_arena, 0)
    assert action.spell != Spell.ZXKUQYB
