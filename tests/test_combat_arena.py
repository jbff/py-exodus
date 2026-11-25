"""Tests for Tactical Combat System (11x11 Conflict Arena) and Combat Resolver."""
import random

import pytest
from py_exodus.assets import MAP_NAME_TO_ID, AssetManager
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
from py_exodus.combat import arena as arena_mod
from py_exodus.combat import resolver as resolver_mod
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
from py_exodus.entities.defs import CreatureDef


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

    # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): encounter size per
    # funcs5.c:1573-1608 (Java party-size formula superseded) — guards always
    # spawn 8 regardless of party size; non-guards roll randint(1, 8).
    # Standard monsters: count in [1, 8]
    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr)
    assert 1 <= len(arena.monsters) <= 8
    # Monsters placed at valid monster_starts
    for m in arena.monsters:
        assert (m.x, m.y) in conflict_map.monster_starts

    # Guards: always spawn the full 8 (clamped only by monster_starts)
    guard_arena = CombatArena(party, conflict_map, creature_tile="guard", asset_mgr=asset_mgr)
    assert len(guard_arena.monsters) == 8


def test_encounter_size_gbc_non_guard_full_range(asset_mgr, conflict_map):
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): encounter size per
    funcs5.c:1573-1608 (Java party-size formula superseded) — a non-guard
    battle rolls random.randint(1, 8) no matter how large the party is; every
    count 1..8 is reachable and party size has no effect (same observed range
    for a 1-member and a 9-member party)."""
    single = Party()
    single.add_member(Character("Solo", "M", Race.HUMAN, Profession.FIGHTER))
    # A 9-member roster exceeds MAX_PARTY_MEMBERS, so it is assigned directly:
    # the spawn count only reads len(party.members) and the GBC rule must be
    # party-size-blind — even a roster larger than the game allows rolls 1..8.
    mega = Party()
    mega.members = [
        Character(f"Hero{i}", "M", Race.HUMAN, Profession.FIGHTER) for i in range(9)
    ]

    for party in (mega, single):
        seen = set()
        for i in range(200):
            random.seed(9000 + i)
            arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr)
            seen.add(len(arena.monsters))
        # Full uniform range reachable, nothing outside 1..8
        assert seen == set(range(1, 9))
        for m in arena.monsters:
            assert (m.x, m.y) in conflict_map.monster_starts


def test_encounter_size_guard_always_eight(asset_mgr, conflict_map):
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): encounter size per
    funcs5.c:1573-1608 (Java party-size formula superseded) — guard battles
    spawn 8 regardless of party size (clamped only by monster_starts)."""
    solo = Party()
    solo.add_member(Character("Solo", "M", Race.HUMAN, Profession.FIGHTER))
    arena = CombatArena(solo, conflict_map, creature_tile="guard", asset_mgr=asset_mgr)
    assert len(arena.monsters) == 8


def test_encounter_size_exodus_map_always_eight(asset_mgr, conflict_map):
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): encounter size per
    funcs5.c:1573-1608 (Java party-size formula superseded) — any battle fought
    on the Castle of Death (inexodus ≡ Maps.EXODUS) spawns 8, guard or not."""
    solo = Party()
    solo.add_member(Character("Solo", "M", Race.HUMAN, Profession.FIGHTER))

    # Explicit context_map_id (overworld call sites thread game_map.id through)
    arena = CombatArena(
        solo,
        conflict_map,
        creature_tile="orc",
        asset_mgr=asset_mgr,
        context_map_id=MAP_NAME_TO_ID["EXODUS"],
    )
    assert len(arena.monsters) == 8

    # Default None falls back to the party's current map id and must keep working
    exodus_party = Party(map_id=MAP_NAME_TO_ID["EXODUS"])
    exodus_party.add_member(Character("Solo2", "M", Race.HUMAN, Profession.FIGHTER))
    fallback_arena = CombatArena(exodus_party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr)
    assert fallback_arena.context_map_id == MAP_NAME_TO_ID["EXODUS"]
    assert len(fallback_arena.monsters) == 8


def test_player_placement(asset_mgr, conflict_map):
    """Members take start tiles by roster index; LairWare places only Good or
    Poisoned members (UltimaSpellCombat.c:887-895), so a dead member gets no
    tile and the living keep their own roster slots. (Java placed corpses;
    LairWare is the rule, user report 2026-11-22.)"""
    party = Party()
    party.add_member(Character("Alive1", "M", Race.HUMAN, Profession.FIGHTER, hp=100))
    party.add_member(Character("Dead1", "F", Race.ELF, Profession.CLERIC, hp=0, status=Status.DEAD))
    party.add_member(Character("Alive2", "M", Race.DWARF, Profession.PALADIN, hp=100))

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr)
    # Alive1 at player_starts[0], Dead1 off the board, Alive2 at [2]
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
    hero = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, dexterity=99, strength=50)
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
    hero = Character("Archer", "M", Race.ELF, Profession.RANGER, dexterity=99, strength=30, weapon=WeaponType.BOW)
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


def test_ranged_attack_flies_over_wall(asset_mgr, conflict_map):
    """LairWare Shoot (UltimaSpellCombat.c:708-731) has no terrain test: the
    arrow passes the wall and reaches the monster (Java stopped it)."""
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
    assert res.attack_res is not None
    assert (3, 2) in res.attack_res.projectile_path


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
    party1.add_member(Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, dexterity=99, strength=50))
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
    party2 = Party(transport=Transport.FOOT)  # LW: only a pirate fought from land leaves a frigate
    party2.add_member(Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, dexterity=99, strength=50))
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
    party3.add_member(Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, dexterity=99, strength=50))
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

    # Monster damage formula — Java Creature.getDamage has no floor
    # (resolver.calculate_monster_damage docstring): small monsters can
    # deal 0, so the assertion is only that the result is non-negative.
    m_dmg = calculate_monster_damage(basehp=48)
    assert 0 <= m_dmg <= 255


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
    hero = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, dexterity=99, strength=50)
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


def test_casting_with_zero_mp_for_zero_cost_spells(asset_mgr, conflict_map, monkeypatch):
    """Verify spells costing 0 MP (Spell A: Repond / Pontori) can be cast even with 0 MP."""
    from py_exodus.combat import magic as magic_mod

    party = Party()
    wiz = Character("Mage", "M", Race.FUZZY, Profession.WIZARD, intelligence=50, mp=0)
    party.add_member(wiz)

    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=3)
    # Pass LW's 50% cast roll: this test pins MP gating only
    # 128 passes the roll; 128 & 3 == 0 then spares every orc (the fight goes on)
    monkeypatch.setattr(magic_mod.random, "randrange", lambda n: 128)
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
    hero = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, strength=50, dexterity=99)
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

    # Melee attack kills the monster; advance past attack projectile so dying flash starts
    combat._execute_action(Action.attack(Direction.NORTH))
    combat.update(0.40)

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


# --- Rolled per-battle HP: LairWare Combat (UltimaSpellCombat.c:867, 901-905)
# RandNum(0, monhpstart[type]) | 0x0F (user ruling 2026-11-25, ledger B-10) ---


def test_monster_hp_rolled_per_battle():
    """Per-battle monster HP is RandNum(0, monhpstart[type]) | 0x0F: the low
    nibble is forced, so HP always ends in 0x0F (floor 15) and tops out at
    the orc's 48 | 0x0F = 63, whatever creatures.xml says (basehp 32)."""
    low_cap_def = CreatureDef(id=30, name="Snapper", tile="orc", basehp=32)
    seen: set[int] = set()
    for i in range(200):
        random.seed(7000 + i)
        monster = CombatMonster(low_cap_def, 3, 3)
        assert monster.hp >= 15  # |0x0F floor
        assert monster.hp & 0x0F == 0x0F  # low nibble forced
        assert monster.hp <= 48 | 0x0F  # the orc's monhpstart, not basehp
        assert monster.max_hp == monster.hp
        seen.add(monster.hp)
    assert 63 in seen
    # The distribution varies per instance, not one fixed value.
    assert len(seen) > 1


def test_monster_hp_roll_cap_is_monhpstart_or_0x0f():
    """For a guard (monhpstart 0xF0) the roll never exceeds 240 | 0x0F."""
    guard_def = CreatureDef(id=6, name="Guard", tile="guard", basehp=128)
    seen = set()
    for i in range(200):
        random.seed(8100 + i)
        monster = CombatMonster(guard_def, 3, 3)
        assert 15 <= monster.hp <= 240 | 0x0F
        seen.add(monster.hp)
    assert max(seen) > 128 | 0x0F  # past the old basehp cap


def test_monster_hp_explicit_definition_override_kept():
    """The CreatureDef fixed-hp override path (hp set explicitly, i.e. hp
    differing from the post_init default hp=basehp) survives the roll."""
    fixed = CreatureDef(id=31, name="Bound Wisp", tile="wisp", basehp=48, hp=100)
    monster = CombatMonster(fixed, 3, 3)
    assert monster.hp == 100
    assert monster.max_hp == 100


# --- GBC ship-battle cannonfire + no-LOS magic poke (2026-11-14) ---------------


def test_ship_party_monster_ranged_is_single_target_projectile(asset_mgr, conflict_map, monkeypatch):
    """Ship-battle monsters use single-target projectiles, not party-wide
    cannonfire: a dragon's fire (LairWare monshoot, UltimaSpellCombat.c:
    1160-1185) hits only the member lined up on its heading."""
    monkeypatch.setattr(arena_mod.random, "randint", lambda a, b: a)  # fire; low damage
    party = Party(transport=Transport.SHIP)
    for i in range(2):
        party.add_member(Character(f"Hero{i}", "M", hp=60, max_hp=60))
    arena = CombatArena(party, conflict_map, creature_tile="dragon", asset_mgr=asset_mgr, monster_count=1)
    arena.player_positions[0] = (3, 5)
    arena.player_positions[1] = (6, 5)
    arena.monsters[0].x, arena.monsters[0].y = 3, 1
    party.members[0].x, party.members[0].y = 3, 5
    party.members[1].x, party.members[1].y = 6, 5

    res = arena._execute_single_monster_ai(arena.monsters[0])
    assert res is not None
    assert res.action_type == "ranged"
    assert not res.message.startswith("Cannonball barrage!")
    assert party.members[0].hp < 60
    assert party.members[1].hp == 60


def test_wizard_with_distant_party_magic_blasts(asset_mgr, conflict_map, monkeypatch):
    """LairWare monmagic (UltimaSpellCombat.c:1125-1153): no adjacent member
    and a caster; RandNum(0, 0xC0) > 127 passes, the slot roll picks slot 0
    (a Good member) and the attack goes through the melee chokepoint."""
    real_randrange = random.randrange
    real_randint = random.randint
    monkeypatch.setattr(
        resolver_mod.random, "randint",
        lambda a, b: 0 if (a, b) == (0, 255) else real_randint(a, b),
    )

    def fake(n):
        value = real_randrange(n)
        return 0 if n == 100 else (129 if n == 193 else value)  # RANGED + blast

    monkeypatch.setattr(arena_mod.random, "randrange", fake)
    monkeypatch.setattr(resolver_mod, "lw_monster_damage_roll", lambda *a, **k: 7)
    monkeypatch.setattr(resolver_mod, "monster_damage_bonus", lambda context_map_id=None: 0)
    monkeypatch.setattr(resolver_mod, "lw_monster_hits", lambda *a, **k: True)
    party = Party()
    hero = Character("Hero", "M", hp=999, max_hp=999)
    party.add_member(hero)
    arena = CombatArena(
        party, conflict_map, creature_tile="wizard",
        asset_mgr=asset_mgr, monster_count=1,
    )
    arena.player_positions[0] = (5, 5)
    hero.x, hero.y = 5, 5
    arena.monsters[0].x, arena.monsters[0].y = 0, 0

    res = arena._execute_single_monster_ai(arena.monsters[0])
    assert res is not None
    assert res.action_type == "ranged"
    # Playtest-1 item 4 affordance: the blast's hit line rides under the
    # "Magic Blast!" feedback (the roll itself went through the melee roll).
    assert res.message == "Magic Blast!\nWizard hits Hero (-7)."
    assert hero.hp == 999 - 7  # single-target roll through the melee chokepoint


def test_adjacent_wizard_attacks_without_the_poke(asset_mgr, conflict_map, monkeypatch):
    """Adjacency blocks the poke: a close member is attacked (LairWare
    `if (zp[0xD0] == 0) goto afternext`, UltimaSpellCombat.c:1117-1118)
    before any magic roll."""
    real_randrange = random.randrange
    poke_rolls: list[int] = []

    def fake(n):
        value = real_randrange(n)
        if n == 193:
            poke_rolls.append(value)
        return value

    monkeypatch.setattr(arena_mod.random, "randrange", fake)
    monkeypatch.setattr(resolver_mod, "lw_monster_damage_roll", lambda *a, **k: 5)
    monkeypatch.setattr(resolver_mod, "lw_monster_hits", lambda *a, **k: True)
    party = Party()
    hero = Character("Hero", "M", hp=999, max_hp=999)
    party.add_member(hero)
    arena = CombatArena(
        party, conflict_map, creature_tile="wizard",
        asset_mgr=asset_mgr, monster_count=1,
    )
    arena.player_positions[0] = (5, 4)
    hero.x, hero.y = 5, 4
    arena.monsters[0].x, arena.monsters[0].y = 5, 5

    res = arena._execute_single_monster_ai(arena.monsters[0])
    assert res is not None
    assert res.action_type == "attack"
    assert res.message != "Magic Blast!"
    assert poke_rolls == []
    assert hero.hp == 999 - 5


# --- Pending item 11 (Java SpellUtil): failed casts keep the caster active ---

def _two_caster_arena(asset_mgr, conflict_map):
    party = Party()
    party.add_member(Character("Mage0", "M", Race.FUZZY, Profession.WIZARD, mp=50))
    party.add_member(Character("Cleric1", "F", Race.ELF, Profession.CLERIC, mp=50))
    # Skeletons: PONTORI's own type, so its gates (not LW's type test,
    # UltimaSpellCombat.c:253) are what these tests reach.
    return CombatArena(party, conflict_map, creature_tile="skeleton",
                       asset_mgr=asset_mgr, monster_count=1)


def test_failed_spell_cast_leaves_caster_active(asset_mgr, conflict_map):
    """Pending item 11 — every SpellUtil.spellCast failure gate
    (SpellUtil.java:24-76: bad target/direction, out of mana, "Can't!" used
    free spell, NEGATE aura) returns false before any finishPlayerTurn call,
    and SpellInputProcessor (SpellInputProcessor.java:63/84/116) ignores the
    result — so the caster REMAINS ACTIVE and the monster phase waits."""
    from py_exodus.aura import AuraType
    from py_exodus.constants import Spell

    arena = _two_caster_arena(asset_mgr, conflict_map)
    assert arena.active_party_member_idx == 0

    # Missing direction gate (SpellUtil.java:41-49) — a pre-execution
    # refusal: executed=False (Task 4 classification)
    res = arena.execute_turn(Action.cast(Spell.MITTAR))
    assert not res.success
    assert res.message == "Thou must indicate a direction to cast the spell!"
    assert res.spell_res.executed is False
    assert res.consume_turn is False
    assert arena.active_party_member_idx == 0
    assert not arena.is_party_round_done

    # Out-of-mana gate (SpellUtil.java:57-60): spend the mage's MP first.
    # Direct-API call (bypassing the menu/letter list): the prevalidation
    # gate fires BEFORE any effect, executed=False — the caster stays active.
    arena.party.members[0].mp = 0
    res = arena.execute_turn(Action.cast(Spell.MITTAR, direction=Direction.NORTH))
    assert not res.success
    assert res.message == "Thou dost not have enough magic points!"
    assert res.spell_res.executed is False
    assert res.consume_turn is False
    assert arena.active_party_member_idx == 0
    assert not arena.is_party_round_done
    arena.party.members[0].mp = 50

    # "Can't!" spent-latch gate (LW g56E7, A-02; refused at the attempt,
    # P-14) — pre-execution refusal: executed=False
    arena.active_party_member_idx = 1
    arena.pontori_latch = True
    res = arena.execute_turn(Action.cast(Spell.PONTORI))
    assert not res.success
    assert res.message == "Can't!"
    assert res.spell_res.executed is False
    assert res.consume_turn is False
    assert arena.active_party_member_idx == 1
    assert not arena.is_party_round_done
    arena.pontori_latch = False

    # NEGATE gate (SpellUtil.java:73-76): mana stays unspent AND turn unspent
    # — pre-execution refusal: executed=False
    arena.party.aura.set(AuraType.NEGATE, 3)
    res = arena.execute_turn(Action.cast(Spell.PONTORI))
    assert not res.success
    assert res.message == "Spell is negated!"
    assert res.spell_res.executed is False
    assert res.consume_turn is False
    assert arena.active_party_member_idx == 1
    assert not arena.is_party_round_done
    assert arena.party.members[1].mp == 50


def test_masskill_gate_failed_cast_consumes_the_turn(asset_mgr, conflict_map, monkeypatch):
    """A PONTORI cast whose 50% roll misses (LW UltimaSpellCombat.c:262-266
    ``if (RandNum(0, 255) < 128) { Failed(); return; }``) runs FAILED through
    the EFFECT branch and the turn is consumed even though success is
    false (no retry on an executed-but-failed cast)."""
    from py_exodus.combat import magic as magic_mod
    from py_exodus.constants import Spell

    random.seed(2026)
    arena = _two_caster_arena(asset_mgr, conflict_map)
    monkeypatch.setattr(magic_mod.random, "randrange", lambda n: 0)  # the roll misses
    arena.active_party_member_idx = 1  # PONTORI is a cleric spell
    before_round = arena.round_count
    assert arena.active_party_member_idx == 1

    res = arena.execute_turn(Action.cast(Spell.PONTORI))
    assert not res.success
    assert res.message == "FAILED"
    assert res.spell_res.executed is True
    assert res.consume_turn is True
    # The consumed turn finished the round: the monster phase ran and the
    # turn order reset to the head of the next round.
    assert arena.round_count == before_round + 1
    assert arena.is_party_round_done is False
    assert arena.active_party_member_idx == 0


def test_altair_executed_consumes_the_turn(asset_mgr, conflict_map):
    """LW UltimaSpellCombat.c:238: Altair is an ordinary cast, so the turn
    is spent (Java's spellAltair never called finishPlayerTurn)."""
    from py_exodus.constants import Spell

    random.seed(2026)
    arena = _two_caster_arena(asset_mgr, conflict_map)
    arena.party.members[0].mp = 99  # ALTAIR costs more than the fixture's 50
    res = arena.execute_turn(Action.cast(Spell.ALTAIR))
    assert res.success
    assert res.spell_res.executed is True
    assert res.consume_turn is True
    assert arena.active_party_member_idx == 1


def test_successful_bolt_still_consumes_the_turn(asset_mgr, conflict_map):
    """Contrast case: a successful combat bolt (MITTAR, SpellUtil.spellMagic
    Attack via Utils.animateMagicAttack) keeps consuming the caster's turn."""
    from py_exodus.constants import Spell

    random.seed(1234)
    arena = _two_caster_arena(asset_mgr, conflict_map)
    res = arena.execute_turn(Action.cast(Spell.MITTAR, direction=Direction.NORTH))
    assert res.success
    assert res.spell_res.executed is True  # Task 4: effect branch ran
    assert res.consume_turn is True
    assert arena.active_party_member_idx == 1


# --- B-01: combat rounds count no moves; AgeChars every 4th round ---
# LairWare UltimaSpellCombat.c:883, 920-923: combat sets Party[3] = 0x80 and
# runs AgeChars at the top of every round, acting every 4th call. No move is
# counted, aboard ship or not (the old ship-once ruling is withdrawn,
# user ruling 2026-11-25).

def _ship_party() -> Party:
    party = Party()
    party.add_member(Character("Sailor", "M", Race.HUMAN, Profession.FIGHTER))
    party.transport = Transport.SHIP
    party.ship_hull = 40
    return party


def test_ship_battle_round_counts_no_move_and_eats_every_fourth_round(
    asset_mgr, conflict_map
):
    random.seed(500)
    party = _ship_party()
    party.members[0].submorsels = 45
    party.members[0].food = 10
    arena = CombatArena(
        party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1
    )
    # combatstart's first AgeChars ticks (gTime[0] starts at 0): 45 - 40.
    assert party.members[0].submorsels == 5
    arena._execute_single_monster_ai = lambda m: None  # type: ignore[method-assign]
    for _ in range(3):
        arena.execute_turn(Action.pass_turn())
    assert party.moves == 0
    assert arena.round_count == 4
    assert party.members[0].food == 10  # calls 2-4 do not tick
    arena.execute_turn(Action.pass_turn())  # call 5 ticks: the pool crosses
    assert party.members[0].food == 9


def test_non_ship_combat_round_counts_no_move(asset_mgr, conflict_map, monkeypatch):
    """No move counter, no hull roll in a land fight either."""
    monkeypatch.setattr("py_exodus.entities.party.random.randint", lambda a, b: 0)
    party = Party()
    party.add_member(Character("Hero", "M", Race.HUMAN, Profession.FIGHTER))
    party.ship_hull = 40
    random.seed(504)
    arena = CombatArena(
        party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1
    )
    moves_before = party.moves

    arena.execute_turn(Action.pass_turn())

    assert party.moves == moves_before
    assert party.ship_hull == 40


def test_ship_battle_killing_action_ages_nothing_more(asset_mgr, conflict_map, monkeypatch):
    """LairWare plrdone (UltimaSpellCombat.c:1083-1094): the action that
    empties the board goes to Victory, not back to combatstart, so the win
    round runs no AgeChars and counts no move."""
    monkeypatch.setattr("py_exodus.entities.party.random.randint", lambda a, b: 0)
    party = _ship_party()
    random.seed(505)
    arena = CombatArena(
        party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1
    )
    arena.monsters[0].take_damage(9999)  # mortally wounded out-of-band
    moves_before = party.moves
    count = party.age_count

    arena.execute_turn(Action.pass_turn())

    assert arena.is_victory
    assert party.moves == moves_before
    assert party.age_count == count


def test_dead_members_are_off_the_board_and_block_nobody(asset_mgr, conflict_map):
    """LairWare (UltimaSpellCombat.c:887-895, 1239-1241): only Good or
    Poisoned members are placed; the dead get no tile and block nobody.
    User report 2026-11-22: a lone survivor was walled in by unseen corpses."""
    party = Party()
    for name in ("A", "B", "C", "D"):
        party.add_member(Character(name, "M", Race.HUMAN, Profession.FIGHTER))
    for m in party.members[1:]:
        m.status = Status.DEAD
        m.hp = 0
    arena = CombatArena(party, conflict_map, creature_tile="orc", asset_mgr=asset_mgr)
    assert set(arena.player_positions) == {0}
    starts = conflict_map.player_starts or [(5, 9), (4, 8), (6, 8), (5, 10)]
    corpse_tile = starts[1]
    assert arena._member_at(*corpse_tile) is None
    assert corpse_tile not in arena._board_positions().values()
