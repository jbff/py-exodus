"""Tests for Full Autoplay ("Watch Mode"): nav, planner, controller, and CLI hook."""
from __future__ import annotations

import pygame
import pytest

from py_exodus.__main__ import GameApp, parse_args
from py_exodus.assets import AssetManager
from py_exodus.autoplay import (
    AutoPlayController,
    Goal,
    evaluate_goal,
    find_2d_step,
    find_dungeon_step,
)
from py_exodus.constants import (
    ArmorType,
    Direction,
    Profession,
    Race,
    Sex,
    Status,
    Transport,
    WeaponType,
)
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.screens.combat_screen import CombatScreen
from py_exodus.screens.final import FinalScreen
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.screens.shrine import ShrineScreen
from py_exodus.screens.town import TownScreen
from py_exodus.state_machine import StateMachine
from py_exodus.world.loader import load_conflict_map, load_dungeon_map, load_map
from py_exodus.world.map import DungeonMap, DungeonTile


@pytest.fixture(scope="module")
def pygame_setup():
    pygame.init()
    if not pygame.font.get_init():
        pygame.font.init()
    yield
    pygame.quit()


@pytest.fixture(scope="module")
def asset_mgr():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


def _make_party(
    level: int = 1,
    exp: int = 0,
    marks: list[int] | None = None,
    cards: list[int] | None = None,
    weapon: WeaponType = WeaponType.DAGGER,
    armor: ArmorType = ArmorType.CLOTH,
    gold: int = 200,
    food: int = 400,
    map_id: int = 0,
    transport: Transport = Transport.FOOT,
    x: int = 44,
    y: int = 20,
) -> Party:
    specs = [
        ("SHADOW", Sex.MALE, Race.FUZZY, Profession.THIEF),
        ("GRUMM", Sex.MALE, Race.DWARF, Profession.FIGHTER),
        ("SERENA", Sex.FEMALE, Race.HUMAN, Profession.CLERIC),
        ("ZIRCON", Sex.MALE, Race.ELF, Profession.WIZARD),
    ]
    party = Party(
        members=[],
        x=x,
        y=y,
        map_id=map_id,
        transport=transport,
        gold=gold,
        food=food,
    )
    for name, sex, race, prof in specs:
        char = Character(name=name, sex=sex, race=race, profession=prof)
        char.level = level
        char.exp = exp
        char.max_hp = level * 100 + 50
        char.hp = char.max_hp
        char.marks = list(marks) if marks is not None else [0, 0, 0, 0]
        char.cards = list(cards) if cards is not None else [0, 0, 0, 0]
        if weapon != WeaponType.NONE:
            char.weapons[weapon] = 1
            char.weapon = weapon
        if armor != ArmorType.NONE:
            char.armors[armor] = 1
            char.armor = armor
        party.add_member(char)
    return party


# ---------------------------------------------------------------------------
# 1. 2D Navigation (find_2d_step)
# ---------------------------------------------------------------------------


def test_find_2d_step_sosaria_wrapping(asset_mgr):
    sosaria = load_map(0, asset_mgr)
    # Column 2 has sailable water at (2, 0) and (2, 63): wrapping north!
    step = find_2d_step(
        sosaria,
        start=(2, 0),
        goals=(2, 63),
        transport=Transport.SHIP,
        wind_direction=Direction.EAST,
    )
    assert step == Direction.NORTH


def test_find_2d_step_force_field_avoidance(asset_mgr):
    sosaria = load_map(0, asset_mgr)
    from copy import deepcopy

    test_map = deepcopy(sosaria)
    # Block (45, 20) with an energy field on grass around (44, 20)
    energy_tile = asset_mgr.get_tile_by_name("energy_field") or next(
        t for t in asset_mgr.tile_defs if t.rule == "energy"
    )
    test_map.set_tile(45, 20, energy_tile)

    party_no_mark = _make_party(marks=[0, 0, 0, 0])
    step_no_mark = find_2d_step(
        test_map,
        start=(44, 20),
        goals=(46, 20),
        transport=Transport.FOOT,
        party=party_no_mark,
    )
    # Cannot step directly EAST onto energy field without Mark of Force
    assert step_no_mark in (Direction.NORTH, Direction.SOUTH)

    party_with_mark = _make_party(marks=[1, 1, 1, 1])
    step_with_mark = find_2d_step(
        test_map,
        start=(44, 20),
        goals=(46, 20),
        transport=Transport.FOOT,
        party=party_with_mark,
    )
    assert step_with_mark == Direction.EAST


def test_find_2d_step_ship_wind_blocking(asset_mgr):
    sosaria = load_map(0, asset_mgr)
    # Open ocean at (50, 13) -> goal (50, 12) (due NORTH).
    # When wind blows SOUTH, sailing NORTH (wind.reverse()) is blocked!
    step_blocked = find_2d_step(
        sosaria,
        start=(50, 13),
        goals=(50, 12),
        transport=Transport.SHIP,
        wind_direction=Direction.SOUTH,
    )
    assert step_blocked is None

    # When becalmed (wind_direction=None), sailing is also blocked!
    step_becalmed = find_2d_step(
        sosaria,
        start=(50, 13),
        goals=(50, 12),
        transport=Transport.SHIP,
        wind_direction=None,
    )
    assert step_becalmed is None

    # When wind blows NORTH, sailing NORTH is allowed!
    step_ok = find_2d_step(
        sosaria,
        start=(50, 13),
        goals=(50, 12),
        transport=Transport.SHIP,
        wind_direction=Direction.NORTH,
    )
    assert step_ok == Direction.NORTH


# ---------------------------------------------------------------------------
# 2. 3D Dungeon Navigation (find_dungeon_step)
# ---------------------------------------------------------------------------


def test_find_dungeon_step_dardin_to_mark_kings_and_back(asset_mgr):
    dmap = load_map(15, asset_mgr)
    # Find MARK_KINGS coordinates in Dardin's Pit
    mark_goals: set[tuple[int, int, int]] = set()
    for z in range(dmap.levels):
        for y in range(dmap.height):
            for x in range(dmap.width):
                if dmap.get_tile(x, y, z) == DungeonTile.MARK_KINGS:
                    mark_goals.add((x, y, z))
    assert mark_goals, "Dardin's Pit should contain MARK_KINGS"

    # Simulate stepping from (1, 1, 0) facing EAST until reaching MARK_KINGS
    x, y, z, facing = 1, 1, 0, Direction.EAST
    steps = 0
    while (x, y, z) not in mark_goals and steps < 200:
        key = find_dungeon_step(dmap, x, y, z, facing, mark_goals)
        assert key is not None, f"Lost path at {(x, y, z, facing)}"
        if key == pygame.K_UP:
            x = (x + facing.dx) % dmap.width
            y = (y + facing.dy) % dmap.height
        elif key == pygame.K_LEFT:
            from py_exodus.world.dungeon import turn_left_dir
            facing = turn_left_dir(facing)
        elif key == pygame.K_RIGHT:
            from py_exodus.world.dungeon import turn_right_dir
            facing = turn_right_dir(facing)
        elif key == pygame.K_d:
            z += 1
        elif key == pygame.K_k:
            z -= 1
        steps += 1

    assert (x, y, z) in mark_goals

    # Now path back to exit (1, 1, 0)
    exit_goals = {(1, 1, 0)}
    steps_back = 0
    while (x, y, z) not in exit_goals and steps_back < 200:
        key = find_dungeon_step(dmap, x, y, z, facing, exit_goals)
        assert key is not None, f"Lost return path at {(x, y, z, facing)}"
        if key == pygame.K_UP:
            x = (x + facing.dx) % dmap.width
            y = (y + facing.dy) % dmap.height
        elif key == pygame.K_LEFT:
            from py_exodus.world.dungeon import turn_left_dir
            facing = turn_left_dir(facing)
        elif key == pygame.K_RIGHT:
            from py_exodus.world.dungeon import turn_right_dir
            facing = turn_right_dir(facing)
        elif key == pygame.K_d:
            z += 1
        elif key == pygame.K_k:
            z -= 1
        steps_back += 1

    assert (x, y, z) == (1, 1, 0)


# ---------------------------------------------------------------------------
# 3. Milestone Goal Evaluator (evaluate_goal)
# ---------------------------------------------------------------------------


def test_evaluate_goal_progression():
    # Empty party -> SETUP_PARTY
    empty = Party(members=[])
    assert evaluate_goal(empty) == Goal.SETUP_PARTY

    # Level 1 without weapons -> OUTFIT_BRITAIN
    unarmed = _make_party(level=1, weapon=WeaponType.NONE, armor=ArmorType.NONE, gold=200)
    assert evaluate_goal(unarmed) == Goal.OUTFIT_BRITAIN

    # Level 1 with weapons -> GRIND_AND_LEVEL
    armed_lvl1 = _make_party(level=1, exp=0)
    assert evaluate_goal(armed_lvl1) == Goal.GRIND_AND_LEVEL

    # Level 5 -> GET_MARK_KINGS
    lvl5 = _make_party(level=5, exp=500, marks=[0, 0, 0, 0])
    assert evaluate_goal(lvl5) == Goal.GET_MARK_KINGS

    # Has Mark of Kings, on foot -> CAPTURE_SHIP
    marked_foot = _make_party(level=5, exp=500, marks=[1, 0, 0, 0], transport=Transport.FOOT)
    assert evaluate_goal(marked_foot) == Goal.CAPTURE_SHIP

    # Has Mark of Kings, on ship -> SAIL_WHIRLPOOL
    marked_ship = _make_party(level=5, exp=500, marks=[1, 0, 0, 0], transport=Transport.SHIP)
    assert evaluate_goal(marked_ship) == Goal.SAIL_WHIRLPOOL

    # In Ambrosia without all cards -> AMBROSIA_CARDS_SHRINES
    ambrosia = _make_party(level=5, exp=500, marks=[1, 0, 0, 0], map_id=13, cards=[1, 0, 0, 0])
    assert evaluate_goal(ambrosia) == Goal.AMBROSIA_CARDS_SHRINES

    # In Ambrosia with all 4 cards -> EXIT_AMBROSIA
    ambrosia_done = _make_party(level=5, exp=500, marks=[1, 0, 0, 0], map_id=13, cards=[1, 1, 1, 1])
    assert evaluate_goal(ambrosia_done) == Goal.EXIT_AMBROSIA

    # Back on Sosaria with all 4 cards, missing Fire/Snake/Force -> GET_REMAINING_MARKS
    need_marks = _make_party(level=6, exp=600, marks=[1, 0, 0, 0], map_id=0, cards=[1, 1, 1, 1])
    assert evaluate_goal(need_marks) == Goal.GET_REMAINING_MARKS

    # All 4 marks + 4 cards, no exotics -> DIG_EXOTICS
    need_exotics = _make_party(level=6, exp=600, marks=[1, 1, 1, 1], map_id=0, cards=[1, 1, 1, 1])
    assert evaluate_goal(need_exotics) == Goal.DIG_EXOTICS

    # All 4 marks + 4 cards + exotic weapon/armor -> CONQUER_EXODUS
    ready_exodus = _make_party(
        level=6,
        exp=600,
        marks=[1, 1, 1, 1],
        map_id=0,
        cards=[1, 1, 1, 1],
        weapon=WeaponType.EXOTIC,
        armor=ArmorType.EXOTIC,
    )
    assert evaluate_goal(ready_exodus) == Goal.CONQUER_EXODUS

    # Exodus defeated -> DONE
    ready_exodus.exodus_defeated = 1
    assert evaluate_goal(ready_exodus) == Goal.DONE


# ---------------------------------------------------------------------------
# 4. AutoPlayController Screen Integration
# ---------------------------------------------------------------------------


def test_autoplay_controller_combat_screen(pygame_setup, asset_mgr):
    party = _make_party(level=5, exp=500)
    sm = StateMachine(asset_mgr=asset_mgr)
    combat_map = load_conflict_map("cnflct_a.json", asset_mgr)
    combat = CombatScreen(
        party=party,
        combat_map=combat_map,
        asset_mgr=asset_mgr,
        encounter_type="goblin",
    )
    sm.push_screen(combat)

    ctrl = AutoPlayController(enabled=True, step_interval=0.05)
    assert combat.auto_combat is False

    # First step should press TAB to enable auto_combat
    ctrl.step(sm)
    assert combat.auto_combat is True

    # Simulate combat finishing
    combat.arena.is_finished = True
    combat.arena.is_defeat = False
    ctrl.step(sm)
    assert sm.current_screen is not combat


def test_autoplay_controller_shrine_screen(pygame_setup, asset_mgr):
    party = _make_party(level=5, gold=400)
    sm = StateMachine(asset_mgr=asset_mgr)
    shrine = ShrineScreen(party=party, shrine_type="wisdom", asset_mgr=asset_mgr)
    sm.push_screen(shrine)

    ctrl = AutoPlayController(enabled=True, step_interval=0.05)
    for _ in range(5):
        if sm.current_screen is not shrine:
            break
        ctrl.step(sm)
    assert sm.current_screen is not shrine


def test_autoplay_controller_overworld_dig_exotics(pygame_setup, asset_mgr):
    party = _make_party(
        level=6,
        exp=600,
        marks=[1, 1, 1, 1],
        cards=[1, 1, 1, 1],
        map_id=0,
        x=33,
        y=3,
    )
    sm = StateMachine(asset_mgr=asset_mgr)
    ow = OverworldScreen(party=party, asset_mgr=asset_mgr)
    sm.push_screen(ow)

    ctrl = AutoPlayController(enabled=True, step_interval=0.01)
    # Drive enough steps for O -> DIG -> member 1..4
    for _ in range(40):
        ctrl.step(sm)
        if all(m.weapons.get(WeaponType.EXOTIC, 0) > 0 for m in party.members):
            break

    assert any(m.weapons.get(WeaponType.EXOTIC, 0) > 0 for m in party.members)


def test_autoplay_controller_exodus_insert_to_final_screen(pygame_setup, asset_mgr):
    party = _make_party(
        level=6,
        exp=600,
        marks=[1, 1, 1, 1],
        cards=[1, 1, 1, 1],
        weapon=WeaponType.EXOTIC,
        armor=ArmorType.EXOTIC,
        map_id=2,
        x=30,
        y=12,
    )
    sm = StateMachine(asset_mgr=asset_mgr)
    town = TownScreen(party=party, map_id=2, asset_mgr=asset_mgr)
    town.avatar_x, town.avatar_y = 30, 12
    sm.push_screen(town)

    ctrl = AutoPlayController(enabled=True, step_interval=0.01)
    for _ in range(100):
        if isinstance(sm.current_screen, FinalScreen):
            break
        ctrl.step(sm)

    assert isinstance(sm.current_screen, FinalScreen)
    assert party.exodus_cards_status == 0xF
    # FinalScreen stops emitting moves cleanly
    assert ctrl.step(sm) is None


# ---------------------------------------------------------------------------
# 5. CLI & Runtime Hook
# ---------------------------------------------------------------------------


def test_cli_autoplay_flag_and_headless_app(pygame_setup):
    args = parse_args(["--autoplay"])
    assert args.autoplay is True

    args_default = parse_args([])
    assert args_default.autoplay is False

    app = GameApp(headless=True, sound_enabled=False, autoplay=True)
    assert app.autoplay.enabled is True
    assert app.autoplay.toggle() is False
    assert app.autoplay.toggle() is True
    faster = app.autoplay.adjust_speed(faster=True)
    assert 0.01 <= faster < 0.08
    slower = app.autoplay.adjust_speed(faster=False)
    assert slower > faster
    app.run(max_frames=5)
    app.cleanup()


def test_autoplay_outfits_fresh_l1_party_in_britain(pygame_setup):
    """Fresh L1 party at Sosaria (44, 20) walks into Britain, buys weapons & Cloth, equips all 4, and exits."""
    from py_exodus.assets import AssetManager
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.state_machine import StateMachine

    am = AssetManager()
    am.load_all()
    party = Party()
    party.add_member(Character("SHADOW", "M", Race.ELF, Profession.THIEF, strength=15, dexterity=25, gold=150))
    party.add_member(Character("GRUMM", "M", Race.DWARF, Profession.FIGHTER, strength=25, dexterity=15, gold=150))
    party.add_member(Character("SERENA", "F", Race.BOBIT, Profession.CLERIC, wisdom=25, strength=15, gold=150))
    party.add_member(Character("ZIRCON", "M", Race.FUZZY, Profession.WIZARD, intelligence=25, strength=15, gold=150))
    party.x, party.y = 44, 20

    sm = StateMachine(asset_mgr=am, audio=None)
    ow = OverworldScreen(party=party, asset_mgr=am, random_encounters_enabled=False)
    ow.creatures = []
    sm.set_screen(ow)

    ctrl = AutoPlayController(enabled=True)
    for _ in range(400):
        ctrl.step(sm)
        if isinstance(sm.current_screen, OverworldScreen) and evaluate_goal(party) == Goal.GRIND_AND_LEVEL:
            break

    assert evaluate_goal(party) == Goal.GRIND_AND_LEVEL
    assert isinstance(sm.current_screen, OverworldScreen)
    assert all(m.weapon != WeaponType.NONE for m in party.members)
    assert all(m.armor == ArmorType.CLOTH for m in party.members)


def test_autoplay_loots_dropped_chest_on_sosaria(pygame_setup):
    """AutoPlayController walks to a dropped chest on Sosaria and opens it (APPAR_UNEM or G)."""
    from py_exodus.assets import AssetManager
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.state_machine import StateMachine

    am = AssetManager()
    am.load_all()
    party = Party()
    party.add_member(Character("SHADOW", "M", Race.ELF, Profession.THIEF, dexterity=25, gold=0))
    party.add_member(Character("GRUMM", "M", Race.DWARF, Profession.FIGHTER, strength=25, gold=0))
    party.add_member(Character("SERENA", "F", Race.BOBIT, Profession.CLERIC, wisdom=25, mp=10, max_mp=25, gold=0))
    party.add_member(Character("ZIRCON", "M", Race.FUZZY, Profession.WIZARD, intelligence=25, gold=0))
    party.x, party.y = 43, 21
    party.dynamic_objects.append({"tile": "chest", "x": 45, "y": 21})

    sm = StateMachine(asset_mgr=am, audio=None)
    ow = OverworldScreen(party=party, asset_mgr=am, random_encounters_enabled=False)
    ow.creatures = []
    sm.set_screen(ow)

    ctrl = AutoPlayController(enabled=True)
    for _ in range(25):
        ctrl.step(sm)
        if not any(o.get("tile") == "chest" for o in party.dynamic_objects):
            break

    assert not any(o.get("tile") == "chest" for o in party.dynamic_objects)
    assert party.gold > 0


def test_find_2d_step_prefer_paths_follows_floor():
    """prefer_paths=True routes along floor tiles rather than cutting straight across grass."""
    from py_exodus.assets import TileDef
    from py_exodus.constants import TileAttrib
    from py_exodus.world.map import GameMap

    floor_t = TileDef(index=8, name="floor", rule="floors", attribs=TileAttrib.NONE)
    grass_t = TileDef(index=1, name="grass", rule="none", attribs=TileAttrib.NONE)
    gm = GameMap(id=3, name="Town", width=5, height=5, border_behavior="exit")
    gm.tiles = [grass_t] * (5 * 5)
    # Path goes SOUTH along x=1 from (1,1) to (1,3) then EAST to (3,3)
    for y in (1, 2, 3):
        gm.set_tile(1, y, floor_t)
    for x in (2, 3):
        gm.set_tile(x, 3, floor_t)

    # Unweighted BFS prefers EAST (first in _CARDINALS); prefer_paths=True follows floor SOUTH
    assert find_2d_step(gm, (1, 1), (3, 3), Transport.FOOT, prefer_paths=False) == Direction.EAST
    assert find_2d_step(gm, (1, 1), (3, 3), Transport.FOOT, prefer_paths=True) == Direction.SOUTH


def test_nearest_shop_town_and_monster_chasing(pygame_setup):
    from py_exodus.assets import AssetManager
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.state_machine import StateMachine

    am = AssetManager()
    am.load_all()
    sosaria = load_map(0, am)
    assert AutoPlayController._nearest_shop_town_portal(sosaria, 10, 44, Transport.FOOT) == (7, 44)  # Grey
    assert AutoPlayController._nearest_shop_town_portal(sosaria, 44, 20, Transport.FOOT) == (46, 19)  # Britain

    party = Party()
    for name in ("A", "B", "C", "D"):
        party.add_member(Character(name, "M", Race.HUMAN, Profession.FIGHTER, weapon=WeaponType.MACE, armor=ArmorType.CLOTH))
    party.x, party.y = 43, 21
    sm = StateMachine(asset_mgr=am, audio=None)
    ow = OverworldScreen(party=party, asset_mgr=am, random_encounters_enabled=False)
    ow.creatures = [{"tile_name": "orc", "x": 45, "y": 21}]
    sm.set_screen(ow)

    ctrl = AutoPlayController(enabled=True)
    key = ctrl.step(sm)
    assert key == pygame.K_RIGHT  # chases orc at (45, 21)


def test_sosaria_patrol_and_shop_towns_are_reachable():
    from py_exodus.assets import AssetManager
    from py_exodus.autoplay.controller import _SHOP_TOWNS, _SOSARIA_PATROL
    from py_exodus.autoplay.nav import can_move_to

    am = AssetManager()
    am.load_all()
    sosaria = load_map(0, am)

    for wp in _SOSARIA_PATROL:
        assert can_move_to(sosaria, wp[0], wp[1], Transport.FOOT), f"Patrol waypoint {wp} not walkable"
        assert find_2d_step(sosaria, (46, 20), wp, Transport.FOOT) is not None, f"Patrol waypoint {wp} unreachable"

    for mid, (px, py, wep_xy, arm_xy) in _SHOP_TOWNS.items():
        assert find_2d_step(sosaria, (46, 20), (px, py), Transport.FOOT) is not None, f"Town {mid} portal unreachable"
        tmap = load_map(mid, am)
        for label, xy in (("weapon", wep_xy), ("armor", arm_xy)):
            assert can_move_to(tmap, xy[0], xy[1], Transport.FOOT), f"Town {mid} {label} {xy} not walkable"
            assert find_2d_step(tmap, (32, 63), xy, Transport.FOOT) is not None, f"Town {mid} {label} {xy} unreachable"



