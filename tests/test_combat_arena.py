"""Tests for Tactical Combat System (11x11 Conflict Arena) and Combat Resolver."""
import pytest
from py_exodus.assets import AssetManager
from py_exodus.world.loader import MapLoader
from py_exodus.world.map import ConflictMap
from py_exodus.entities.party import Party, PartyMember
from py_exodus.entities.character import Character
from py_exodus.constants import (
    ArmorType,
    Direction,
    Profession,
    Race,
    Status,
    TileAttrib,
    Transport,
    WeaponType,
)
from py_exodus.combat.arena import (
    Action,
    ActionType,
    CombatArena,
    CombatMonster,
)
from py_exodus.combat.resolver import (
    AttackResult,
    calculate_monster_damage,
    calculate_player_damage,
    resolve_monster_attack,
    resolve_player_attack,
    roll_hit,
    trace_projectile_path,
)


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


def test_combat_init_and_turn(asset_mgr, conflict_map):
    party = Party()
    party.add_member(Character("Hero", "M", Race.HUMAN, Profession.FIGHTER))

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr)
    assert len(arena.monsters) >= 1
    assert arena.active_party_member_idx == 0
    assert not arena.is_finished
    assert not arena.is_victory
    assert not arena.is_defeat


def test_monster_spawn_crslots_and_guards(asset_mgr, conflict_map):
    # Party with 4 living members
    party = Party()
    for i in range(4):
        party.add_member(Character(f"Hero{i}", "M", Race.HUMAN, Profession.FIGHTER))

    # Standard monsters: count in [1, 8]
    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr)
    assert 1 <= len(arena.monsters) <= 8
    # Monsters placed at valid monster_starts
    for m in arena.monsters:
        assert (m.x, m.y) in conflict_map.monster_starts

    # Guards: always spawn max (8 for 4 members)
    guard_arena = CombatArena(party, conflict_map, creature_tile="guard", asset_mgr=asset_mgr)
    assert len(guard_arena.monsters) == 8


def test_player_placement(asset_mgr, conflict_map):
    party = Party()
    party.add_member(Character("Alive1", "M", Race.HUMAN, Profession.FIGHTER, hp=100))
    party.add_member(Character("Dead1", "F", Race.ELF, Profession.CLERIC, hp=0, status=Status.DEAD))
    party.add_member(Character("Alive2", "M", Race.DWARF, Profession.PALADIN, hp=100))

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr)
    # Alive1 at player_starts[0], Alive2 at player_starts[2]
    assert 0 in arena.player_positions
    assert 1 not in arena.player_positions
    assert 2 in arena.player_positions

    assert arena.player_positions[0] == conflict_map.player_starts[0]
    assert arena.player_positions[2] == conflict_map.player_starts[2]


def test_player_movement_and_terrain_collision(asset_mgr, conflict_map):
    party = Party()
    party.add_member(Character("Hero", "M", Race.HUMAN, Profession.FIGHTER))

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    start_pos = arena.player_positions[0]

    # Move north
    res = arena.execute_player_action(0, Action.move(Direction.NORTH))
    expected_pos = (start_pos[0], start_pos[1] - 1)
    # If open tile, moved
    if res.success:
        assert arena.player_positions[0] == expected_pos


def test_player_flee_off_boundary(asset_mgr, conflict_map):
    party = Party()
    party.add_member(Character("Hero", "M", Race.HUMAN, Profession.FIGHTER))

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    # Position hero on southern edge (y=10)
    arena.player_positions[0] = (5, 10)

    # Step South off map (y=11 is out of bounds)
    res = arena.execute_player_action(0, Action.move(Direction.SOUTH))
    assert res.fled
    assert party.members[0].fled
    assert arena.is_finished
    assert arena.is_fled
    assert not arena.is_defeat
    assert not arena.is_victory


def test_turn_sequencing_skips_disabled_members(asset_mgr, conflict_map):
    party = Party()
    party.add_member(Character("P0", "M", Race.HUMAN, Profession.FIGHTER))
    party.add_member(Character("P1", "F", Race.ELF, Profession.CLERIC, hp=0, status=Status.DEAD))
    party.add_member(Character("P2", "M", Race.DWARF, Profession.PALADIN))

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=2)
    assert arena.active_party_member_idx == 0

    # P0 passes
    arena.execute_player_action(0, Action.pass_turn())
    # Should skip P1 (dead) and advance to P2
    assert arena.active_party_member_idx == 2

    # P2 passes -> round finishes
    arena.execute_player_action(2, Action.pass_turn())
    assert arena.is_party_round_done


def test_player_melee_attack_and_exp_award(asset_mgr, conflict_map):
    party = Party()
    # High dexterity ensures hit
    hero = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, dexterity=50, strength=50)
    party.add_member(hero)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    # Position hero at (5, 5) and orc at (5, 4) - North of hero
    arena.player_positions[0] = (5, 5)
    monster = arena.monsters[0]
    monster.x = 5
    monster.y = 4
    monster.hp = 5  # low hp to verify kill

    initial_exp = hero.exp
    res = arena.execute_player_action(0, Action.attack(Direction.NORTH))
    assert res.success
    assert res.attack_res is not None
    assert res.attack_res.hit
    assert res.attack_res.killed
    assert hero.exp > initial_exp
    # Monster dead and removed
    assert len(arena.monsters) == 0
    # Victory triggered
    assert arena.is_victory
    assert arena.is_finished


def test_ranged_projectile_tracing_and_attack(asset_mgr, conflict_map):
    party = Party()
    # Hero equipped with Bow (ranged)
    hero = Character("Archer", "M", Race.ELF, Profession.RANGER, dexterity=50, strength=30, weapon=WeaponType.BOW)
    party.add_member(hero)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    # Column 3 has clear floor/grass from y=1 to y=10
    arena.player_positions[0] = (3, 7)
    monster = arena.monsters[0]
    monster.x = 3
    monster.y = 3  # 4 tiles north in open corridor

    res = arena.execute_player_action(0, Action.attack(Direction.NORTH))
    assert res.success
    assert res.attack_res is not None
    assert res.attack_res.hit
    # Projectile path traversed from (3, 6) to (3, 3)
    assert (3, 3) in res.attack_res.projectile_path


def test_ranged_attack_blocked_by_wall(asset_mgr, conflict_map):
    # Set tile (3, 5) to solid wall
    wall_tile = asset_mgr.tile_defs_by_name.get("wall") or asset_mgr.tile_defs_by_name.get("brick_wall")
    if wall_tile is not None:
        conflict_map.set_tile(3, 5, wall_tile)

    party = Party()
    hero = Character("Archer", "M", Race.ELF, Profession.RANGER, weapon=WeaponType.BOW)
    party.add_member(hero)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    arena.player_positions[0] = (3, 7)
    monster = arena.monsters[0]
    monster.x = 3
    monster.y = 2  # Behind wall at (3, 5)

    res = arena.execute_player_action(0, Action.attack(Direction.NORTH))
    # Projectile stopped at wall (3, 5), did not reach monster at (3, 2)
    assert res.attack_res is not None
    assert (3, 2) not in res.attack_res.projectile_path
    assert not res.attack_res.hit


def test_monster_ai_advancement_and_melee_attack(asset_mgr, conflict_map):
    party = Party()
    hero = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, hp=100)
    party.add_member(hero)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    # Open floor corridor at column 3
    arena.player_positions[0] = (3, 5)
    monster = arena.monsters[0]
    monster.x = 3
    monster.y = 3  # 2 tiles away on open floor

    # Monster turns: should advance towards player
    monster_results = arena.execute_monster_turns()
    assert len(monster_results) >= 1
    assert monster_results[0].action_type in ("advance", "attack")
    # Monster should be adjacent now (at 3, 4)
    assert monster.x == 3
    assert monster.y == 4

    # Next monster turn: adjacent, monster should attack
    monster_results_2 = arena.execute_monster_turns()
    assert len(monster_results_2) >= 1
    assert monster_results_2[0].action_type == "attack"


def test_poison_tick_and_succumb(asset_mgr, conflict_map):
    party = Party()
    hero = Character("PoisonedHero", "M", Race.HUMAN, Profession.FIGHTER, hp=2, status=Status.POISONED)
    party.add_member(hero)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    # Move monster far away so it doesn't kill hero in melee
    arena.monsters[0].x = 0
    arena.monsters[0].y = 0
    arena.player_positions[0] = (10, 10)

    # Monster turns execute, then poison tick applies
    arena.execute_monster_turns()
    # Hero had 2 HP, took 2 poison damage -> died
    assert hero.hp == 0
    assert hero.status == Status.DEAD
    assert arena.is_defeat
    assert arena.is_finished


def test_chest_spawning_rules(asset_mgr, conflict_map):
    # 1. Normal land victory -> Spawns chest
    party1 = Party(transport=Transport.FOOT)
    party1.add_member(Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, dexterity=50, strength=50))
    arena1 = CombatArena(party1, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    arena1.monsters[0].hp = 1
    arena1.monsters[0].x = 5
    arena1.monsters[0].y = 4
    arena1.player_positions[0] = (5, 5)
    arena1.execute_player_action(0, Action.attack(Direction.NORTH))
    assert arena1.is_victory
    assert arena1.chest_spawned

    # 2. Ship combat victory -> No chest spawned
    party2 = Party(transport=Transport.SHIP)
    party2.add_member(Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, dexterity=50, strength=50))
    arena2 = CombatArena(party2, conflict_map, creature_tile="pirate", asset_mgr=asset_mgr, monster_count=1)
    arena2.monsters[0].hp = 1
    arena2.monsters[0].x = 5
    arena2.monsters[0].y = 4
    arena2.player_positions[0] = (5, 5)
    arena2.execute_player_action(0, Action.attack(Direction.NORTH))
    assert arena2.is_victory
    assert not arena2.chest_spawned

    # 3. Creature with nochest -> No chest spawned
    party3 = Party(transport=Transport.FOOT)
    party3.add_member(Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, dexterity=50, strength=50))
    arena3 = CombatArena(party3, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    arena3.monsters[0].no_chest = True
    arena3.creature_def.no_chest = True
    arena3.monsters[0].hp = 1
    arena3.monsters[0].x = 5
    arena3.monsters[0].y = 4
    arena3.player_positions[0] = (5, 5)
    arena3.execute_player_action(0, Action.attack(Direction.NORTH))
    assert arena3.is_victory
    assert not arena3.chest_spawned


def test_defeat_when_all_party_members_slain(asset_mgr, conflict_map):
    party = Party()
    hero = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, hp=1)
    party.add_member(hero)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    arena.monsters[0].x = 5
    arena.monsters[0].y = 4
    arena.player_positions[0] = (5, 5)

    # Directly apply lethal damage to hero
    hero.hp = 0
    hero.status = Status.DEAD

    # Execute monster turns to evaluate party status
    arena.execute_monster_turns()
    assert arena.is_defeat
    assert not arena.is_victory
    assert arena.is_finished


def test_combat_resolver_calculations(asset_mgr):
    # Hit roll: dex >= 40 gives bonus 255 -> always > defense 128
    assert roll_hit(255, 128) is True

    # Player damage formula
    char = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, strength=20)
    sword_def = asset_mgr.get_weapon("sword")
    dmg = calculate_player_damage(char, sword_def)
    assert sword_def.dmin <= dmg <= 255

    # Monster damage formula
    m_dmg = calculate_monster_damage(basehp=48)
    assert m_dmg >= 1
