"""Tests for Tactical Combat System (11x11 Conflict Arena) and Combat Resolver."""
import pytest
from py_exodus.assets import AssetManager
from py_exodus.world.loader import MapLoader
from py_exodus.entities.party import Party
from py_exodus.entities.character import Character
from py_exodus.constants import (
    Direction,
    Profession,
    Race,
    Status,
    Transport,
    WeaponType,
)
from py_exodus.combat.arena import (
    Action,
    CombatArena,
    CombatMonster,
)
from py_exodus.combat.resolver import (
    calculate_monster_damage,
    calculate_player_damage,
    resolve_monster_attack,
    roll_hit,
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
    """Java CombatScreen.java:125-147 — every member gets combat coordinates by
    roster index, DEAD members included (their corpses occupy a tile and block
    creatures: hasBlockingCombatPlayerAt skips only fled members)."""
    party = Party()
    party.add_member(Character("Alive1", "M", Race.HUMAN, Profession.FIGHTER, hp=100))
    party.add_member(Character("Dead1", "F", Race.ELF, Profession.CLERIC, hp=0, status=Status.DEAD))
    party.add_member(Character("Alive2", "M", Race.DWARF, Profession.PALADIN, hp=100))

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr)
    # Alive1 at player_starts[0], Dead1's corpse at [1], Alive2 at [2]
    assert 0 in arena.player_positions
    assert 1 in arena.player_positions
    assert 2 in arena.player_positions

    assert arena.player_positions[0] == conflict_map.player_starts[0]
    assert arena.player_positions[1] == conflict_map.player_starts[1]
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


def test_player_off_edge_move_blocked(asset_mgr, conflict_map):
    """Java CombatScreen.preMove (CombatScreen.java:413-446): FLEE is commented
    out; stepping off the arena plays BLOCKED and consumes the move."""
    party = Party()
    party.add_member(Character("Hero", "M", Race.HUMAN, Profession.FIGHTER))

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    arena.player_positions[0] = (5, 10)

    res = arena.execute_player_action(0, Action.move(Direction.SOUTH))
    assert not res.success
    assert arena.player_positions[0] == (5, 10)
    assert not party.members[0].fled
    assert not arena.is_finished
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
    monster.hp = 1  # low hp to verify kill

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

    # 2. Pirate defeated on unwalkable water -> No chest, boardable frigate
    #    at the creature's tile (Java GameScreen.java:425-431)
    party2 = Party(transport=Transport.SHIP)
    party2.add_member(Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, dexterity=50, strength=50))
    arena2 = CombatArena(party2, conflict_map, creature_tile="pirate", asset_mgr=asset_mgr, monster_count=1,
                         encounter_x=21, encounter_y=7, encounter_tile_walkable=False)
    arena2.monsters[0].hp = 1
    arena2.monsters[0].x = 5
    arena2.monsters[0].y = 4
    arena2.player_positions[0] = (5, 5)
    arena2.execute_player_action(0, Action.attack(Direction.NORTH))
    assert arena2.is_victory
    assert not arena2.chest_spawned
    # Defeated pirate leaves behind boardable frigate
    assert any(obj.get("tile") == "frigate" for obj in party2.dynamic_objects)

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


def test_poisonous_monster_fatal_blow_preserves_dead_status(asset_mgr, monkeypatch):
    # Verify that fatal damage from a poisonous monster leaves character DEAD, not POISONED
    m_def = asset_mgr.get_creature("snake")
    if m_def is None:
        from py_exodus.entities.defs import CreatureDef
        m_def = CreatureDef(id=99, name="Viper", tile="snake", basehp=48, poisons=True)
    else:
        m_def.poisons = True

    monster = CombatMonster(m_def, x=5, y=5)
    char = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, hp=1, status=Status.GOOD)

    # Over 20 trials, every lethal hit must result in Status.DEAD and never
    # Status.POISONED. Java's melee creatureAction has no poison path at all
    # (CombatScreen.java:720-745); death is newHp < 0 (Party.java:565), so the
    # blow is made decisively fatal with a patched damage roll.
    from py_exodus.combat import resolver as resolver_mod

    monkeypatch.setattr(resolver_mod, "calculate_monster_damage", lambda basehp=48: 5)
    for _ in range(20):
        char.hp = 1
        char.status = Status.GOOD
        res = resolve_monster_attack(monster=monster, target_player=char)
        if res.hit:
            assert res.killed
            assert char.hp == 0
            assert char.status == Status.DEAD
            assert char.status != Status.POISONED
            assert not res.poisoned


def test_victory_spawns_chest_for_overworld_only_not_on_combat_map(asset_mgr, conflict_map):
    party = Party()
    hero = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, dexterity=50, strength=50)
    party.add_member(hero)
    party.x = 20
    party.y = 20
    party.dynamic_objects.clear()

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    arena.player_positions[0] = (5, 5)
    monster = arena.monsters[0]
    monster.x = 5
    monster.y = 4
    monster.hp = 1

    res = arena.execute_player_action(0, Action.attack(Direction.NORTH))
    assert res.success
    assert arena.is_victory
    assert arena.is_finished

    # Verify no tile on the 11x11 combat arena map was changed to a chest
    for y in range(conflict_map.height):
        for x in range(conflict_map.width):
            t = conflict_map.get_tile(x, y)
            assert getattr(t, "name", "").lower() != "chest"

    # Verify chest was registered in party.dynamic_objects for world map pickup
    assert len(party.dynamic_objects) >= 1
    assert any(obj.get("tile") == "chest" for obj in party.dynamic_objects)


def test_player_projectile_passes_through_party_members(asset_mgr, conflict_map):
    """Verify player projectile passes cleanly through party members to hit the enemy beyond."""
    party = Party()
    # Wizard in back at (5, 9)
    wiz = Character("Mage", "M", Race.FUZZY, Profession.WIZARD, intelligence=50, mp=50)
    # Fighter in front at (5, 8)
    front = Character("Knight", "M", Race.HUMAN, Profession.FIGHTER, strength=50)
    party.add_member(wiz)
    party.add_member(front)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    arena.player_positions[0] = (5, 9)
    arena.player_positions[1] = (5, 8)
    monster = arena.monsters[0]
    monster.x = 5
    monster.y = 5
    monster.hp = 100

    from py_exodus.constants import Spell
    res = arena.execute_player_action(0, Action.cast(Spell.MITTAR, direction=Direction.NORTH))
    assert res.success
    # The projectile must NOT stop at the party member at (5, 8), it must reach the monster at (5, 5)
    assert res.spell_res.hit
    assert res.spell_res.target_pos == (5, 5)
    assert (5, 8) in res.spell_res.projectile_path
    assert monster.hp < 100


def test_casting_with_zero_mp_for_zero_cost_spells(asset_mgr, conflict_map):
    """Verify spells costing 0 MP (Spell A: Repond / Pontori) can be cast even with 0 MP."""
    party = Party()
    wiz = Character("Mage", "M", Race.FUZZY, Profession.WIZARD, intelligence=50, mp=0)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="giant", asset_mgr=asset_mgr, monster_count=3)
    from py_exodus.constants import Spell
    # Wizard Spell A (REPOND) costs 0 MP and should succeed even with 0 MP
    res = arena.execute_player_action(0, Action.cast(Spell.REPOND))
    assert res.success

    # Wizard Spell B (MITTAR) costs 5 MP and should fail with 0 MP
    res_b = arena.execute_player_action(0, Action.cast(Spell.MITTAR, direction=Direction.NORTH))
    assert not res_b.success
    assert "not enough" in res_b.message.lower() or "magic points" in res_b.message.lower()


def test_dying_monster_visible_during_attack_burst(asset_mgr, conflict_map):
    """Verify dead monster remains in dying_monsters during hit animation and then disappears."""
    import pygame
    party = Party()
    hero = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, strength=50, dexterity=50)
    party.add_member(hero)

    from py_exodus.screens.combat_screen import CombatScreen
    combat = CombatScreen(party=party, combat_map=conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    combat.arena.player_positions[0] = (5, 5)
    monster = combat.arena.monsters[0]
    monster.x = 5
    monster.y = 4
    monster.hp = 1

    combat.combat_fx.clear()
    combat.dying_monsters.clear()

    # Melee attack kills the monster
    combat._execute_action(Action.attack(Direction.NORTH))

    # Monster is dead in arena, but registered in dying_monsters for the hit animation
    assert len(combat.dying_monsters) == 1
    assert combat.dying_monsters[0]["x"] == 5
    assert combat.dying_monsters[0]["y"] == 4

    # Render while dying
    surf = pygame.Surface((640, 400))
    combat.render(surf)

    # After timer expires (0.35s+), dying monster is cleared
    combat.update(0.40)
    assert len(combat.dying_monsters) == 0

