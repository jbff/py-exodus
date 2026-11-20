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
        char = Character(name=name, sex=sex, race=race, profession=prof, gold=gold)
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
    armed_lvl1 = _make_party(level=1, exp=0, gold=0)
    assert evaluate_goal(armed_lvl1) == Goal.GRIND_AND_LEVEL

    # Wizard who threw their last Dagger (WeaponType.NONE, no spares) stays in GRIND_AND_LEVEL
    armed_lvl1.members[3].profession = Profession.WIZARD
    armed_lvl1.members[3].weapon = WeaponType.NONE
    armed_lvl1.members[3].weapons.clear()
    armed_lvl1.members[3].gold = 20
    assert evaluate_goal(armed_lvl1) == Goal.GRIND_AND_LEVEL

    # Level 5 -> GET_MARK_KINGS
    lvl5 = _make_party(level=5, exp=500, marks=[0, 0, 0, 0], gold=0)
    assert evaluate_goal(lvl5) == Goal.GET_MARK_KINGS

    # Has Mark of Kings, on foot without exotics -> CAPTURE_SHIP
    marked_foot = _make_party(level=5, exp=500, marks=[1, 0, 0, 0], transport=Transport.FOOT, gold=0)
    assert evaluate_goal(marked_foot) == Goal.CAPTURE_SHIP

    # Has Mark of Kings, on ship without exotics -> DIG_EXOTICS
    marked_ship_no_ex = _make_party(level=5, exp=500, marks=[1, 0, 0, 0], transport=Transport.SHIP, gold=0)
    assert evaluate_goal(marked_ship_no_ex) == Goal.DIG_EXOTICS

    # Has all Marks, Exotics, keys, and >=1500g on ship -> SAIL_WHIRLPOOL
    marked_ship = _make_party(level=5, exp=500, marks=[1, 1, 1, 1], transport=Transport.SHIP, gold=1500)
    marked_ship.members[0].keys = 2
    for m in marked_ship.members:
        m.weapons[WeaponType.EXOTIC] = 1
        m.armors[ArmorType.EXOTIC] = 1
    assert evaluate_goal(marked_ship) == Goal.SAIL_WHIRLPOOL

    # OverworldScreen map_id=13 overrides stale party.map_id=0 for Ambrosia (requires keys for Death/Moons)
    marked_foot.members[0].keys = 1
    assert evaluate_goal(marked_foot, map_id=13) == Goal.AMBROSIA_CARDS_SHRINES

    # Prematurely entering Ambrosia (below L5, missing Mark of Kings, or 0 keys) -> EXIT_AMBROSIA
    assert evaluate_goal(lvl5, map_id=13) == Goal.EXIT_AMBROSIA
    marked_foot.members[0].keys = 0
    assert evaluate_goal(marked_foot, map_id=13) == Goal.EXIT_AMBROSIA

    # In Ambrosia without all cards -> AMBROSIA_CARDS_SHRINES
    ambrosia = _make_party(level=5, exp=500, marks=[1, 0, 0, 0], map_id=13, cards=[1, 0, 0, 0])
    ambrosia.members[0].keys = 1
    assert evaluate_goal(ambrosia) == Goal.AMBROSIA_CARDS_SHRINES

    # In Ambrosia with all 4 cards -> EXIT_AMBROSIA
    ambrosia_done = _make_party(level=5, exp=500, gold=0, marks=[1, 0, 0, 0], map_id=13, cards=[1, 1, 1, 1])
    assert evaluate_goal(ambrosia_done) == Goal.EXIT_AMBROSIA

    # On Sosaria with exotics, missing Fire/Snake/Force -> GET_REMAINING_MARKS
    need_marks = _make_party(
        level=6, exp=600, marks=[1, 0, 0, 0], map_id=0, cards=[1, 1, 1, 1],
        weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC, gold=0,
    )
    assert evaluate_goal(need_marks) == Goal.GET_REMAINING_MARKS

    # All 4 marks + 4 cards on ship, no exotics -> DIG_EXOTICS
    need_exotics = _make_party(level=6, exp=600, marks=[1, 1, 1, 1], map_id=0, cards=[1, 1, 1, 1], transport=Transport.SHIP)
    assert evaluate_goal(need_exotics) == Goal.DIG_EXOTICS

    # All 4 marks + 4 cards + exotic weapon/armor + L25 -> CONQUER_EXODUS (L18 grinds to L25 first)
    need_l25 = _make_party(
        level=18,
        exp=1700,
        marks=[1, 1, 1, 1],
        map_id=0,
        cards=[1, 1, 1, 1],
        weapon=WeaponType.EXOTIC,
        armor=ArmorType.EXOTIC,
    )
    assert evaluate_goal(need_l25) == Goal.GRIND_AND_LEVEL

    ready_exodus = _make_party(
        level=25,
        exp=2400,
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


def _non_canonical_party(level: int = 5) -> Party:
    """Four wizards: a plausible user party, but not what autoplay supports."""
    party = _make_party(level=level)
    for member in party.members:
        member.profession = Profession.WIZARD
    return party


def test_autoplay_refuses_non_canonical_party(pygame_setup, asset_mgr):
    """Step-time guard: a user-built 4-wizard party must disable autoplay."""
    party = _non_canonical_party()
    sm = StateMachine(asset_mgr=asset_mgr)
    ow = OverworldScreen(party=party, asset_mgr=asset_mgr)
    sm.push_screen(ow)

    ctrl = AutoPlayController(enabled=True)
    ctrl.step(sm)
    assert ctrl.enabled is False
    assert sm.autoplay_enabled is False


def test_f9_toggle_refused_on_non_canonical_party(pygame_setup, asset_mgr):
    """Toggle gate: F9 on a non-canonical party must not engage autoplay."""
    from py_exodus.screens.overworld import OverworldScreen as _OW

    party = _non_canonical_party()
    sm = StateMachine(asset_mgr=asset_mgr)
    sm.push_screen(_OW(party=party, asset_mgr=asset_mgr))

    ctrl = AutoPlayController()
    assert ctrl.toggle() is True
    assert ctrl.can_engage(sm) is False


def test_canonical_party_engages(pygame_setup, asset_mgr):
    party = _make_party(level=5)
    sm = StateMachine(asset_mgr=asset_mgr)
    sm.push_screen(OverworldScreen(party=party, asset_mgr=asset_mgr))

    ctrl = AutoPlayController()
    ctrl.toggle()
    assert ctrl.can_engage(sm) is True
    ctrl.step(sm)
    assert ctrl.enabled is True


def test_party_member_deaths_do_not_trip_composition_guard(pygame_setup, asset_mgr):
    """Wipes must disable autoplay through the death path, not composition."""
    party = _make_party(level=5)
    for member in party.members:
        member.status = Status.DEAD
    sm = StateMachine(asset_mgr=asset_mgr)
    sm.push_screen(OverworldScreen(party=party, asset_mgr=asset_mgr))

    ctrl = AutoPlayController(enabled=True)
    # Composition still counts as canonical (dead members stay listed);
    # the party-wipe branch disables separately in step().
    assert ctrl._party_is_canonical(sm.current_screen) is True


def test_tab_auto_combat_refused_on_non_canonical_party(
    pygame_setup, asset_mgr, monkeypatch
):
    """neural-net branch rule: TAB auto-combat needs T+F+C+W, also for F9-less users."""
    import pygame as pg

    combat_map = load_conflict_map("cnflct_a.json", asset_mgr)
    party = _non_canonical_party(level=5)
    combat = CombatScreen(
        party=party,
        combat_map=combat_map,
        asset_mgr=asset_mgr,
        encounter_type="goblin",
    )
    sm = StateMachine(asset_mgr=asset_mgr)
    sm.push_screen(combat)

    sm.handle_event(pg.event.Event(pg.KEYDOWN, key=pg.K_TAB, mod=0, unicode="\t"))
    assert combat.auto_combat is False

    canonical = _make_party(level=5)
    combat2 = CombatScreen(
        party=canonical,
        combat_map=combat_map,
        asset_mgr=asset_mgr,
        encounter_type="goblin",
    )
    sm2 = StateMachine(asset_mgr=asset_mgr)
    sm2.push_screen(combat2)
    sm2.handle_event(pg.event.Event(pg.KEYDOWN, key=pg.K_TAB, mod=0, unicode="\t"))
    assert combat2.auto_combat is True


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

    assert any(
        m.weapon == WeaponType.EXOTIC or m.weapons.get(WeaponType.EXOTIC, 0) > 0
        for m in party.members
    )


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
    import random
    from py_exodus.assets import AssetManager
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.state_machine import StateMachine

    random.seed(42)

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
    import random
    from py_exodus.assets import AssetManager
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.state_machine import StateMachine

    random.seed(42)

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
    import random
    from py_exodus.assets import AssetManager
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.state_machine import StateMachine

    random.seed(42)

    am = AssetManager()
    am.load_all()
    sosaria = load_map(0, am)
    assert AutoPlayController._nearest_shop_town_portal(sosaria, 10, 44, Transport.FOOT) == (7, 44)  # Grey
    assert AutoPlayController._nearest_shop_town_portal(sosaria, 44, 20, Transport.FOOT) == (46, 19)  # Britain

    party = Party()
    # Canonical composition (the neural-net branch only supports autoplay on
    # Thief+Fighter+Cleric+Wizard parties; other shapes are refused).
    for name, prof in zip(
        ("A", "B", "C", "D"),
        (Profession.THIEF, Profession.FIGHTER, Profession.CLERIC, Profession.WIZARD),
    ):
        party.add_member(Character(name, "M", Race.HUMAN, prof, weapon=WeaponType.MACE, armor=ArmorType.CLOTH, gold=0))
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


def test_equipment_upgrades_hand_and_dawn(pygame_setup):
    """Chest loot is handed to the best-fit member and worn; Dawn upgrades are targeted as gold accumulates."""
    from py_exodus.assets import AssetManager
    from py_exodus.autoplay.equipment import best_shop_upgrade
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.state_machine import StateMachine

    am = AssetManager()
    am.load_all()
    party = Party()
    party.add_member(Character("SHADOW", "M", Race.ELF, Profession.THIEF, weapon=WeaponType.SLING, armor=ArmorType.CLOTH, gold=0))
    party.add_member(Character("GRUMM", "M", Race.DWARF, Profession.FIGHTER, weapon=WeaponType.MACE, armor=ArmorType.CLOTH, gold=0))
    party.add_member(Character("SERENA", "F", Race.BOBIT, Profession.CLERIC, weapon=WeaponType.MACE, armor=ArmorType.CLOTH, gold=0))
    party.add_member(Character("ZIRCON", "M", Race.FUZZY, Profession.WIZARD, weapon=WeaponType.DAGGER, armor=ArmorType.CLOTH, gold=0))
    # ZIRCON (Wizard, cannot wear Chain) finds Chain Mail in a chest
    party.members[3].armors[ArmorType.CHAIN] = 1

    sm = StateMachine(asset_mgr=am, audio=None)
    ow = OverworldScreen(party=party, asset_mgr=am, random_encounters_enabled=False)
    ow.creatures = []
    sm.set_screen(ow)

    ctrl = AutoPlayController(enabled=True)
    for _ in range(15):
        ctrl.step(sm)
        if party.members[1].armor == ArmorType.CHAIN:
            break
    assert party.members[1].armor == ArmorType.CHAIN
    assert party.members[3].armors.get(ArmorType.CHAIN, 0) == 0

    # With 450g pooled, Fighter targets Dawn's Axe +2 (400g, dawn_only=True)
    party.members[2].gold = 450
    up = best_shop_upgrade(party)
    assert up is not None
    assert up.member_idx == 2
    assert up.dawn_only is True
    assert up.item_letter == "i"  # Axe +2

    # Equipped Exotics + L25 count toward Goal.CONQUER_EXODUS
    for m in party.members:
        m.level = 25
        m.exp = 2400
        m.marks = [1, 1, 1, 1]
        m.cards = [1, 1, 1, 1]
        m.weapon = WeaponType.EXOTIC
        m.armor = ArmorType.EXOTIC
    assert evaluate_goal(party) == Goal.CONQUER_EXODUS


def test_profession_equipment_tables_match_xml_and_town_join_gold(pygame_setup):
    """PROFESSION_WEAPONS/ARMORS match AssetManager XML rules; TownScreen pools gold with J and exits for Dawn."""
    from py_exodus.assets import AssetManager
    from py_exodus.autoplay.equipment import PROFESSION_ARMORS, PROFESSION_WEAPONS
    from py_exodus.screens.town import TownScreen
    from py_exodus.state_machine import StateMachine

    am = AssetManager("data")
    am.load_all()

    for prof in Profession:
        expected_w = {
            wt for wt in WeaponType if wt != WeaponType.NONE and am.get_weapon(wt.name.lower()).can_use(prof)
        }
        expected_a = {
            at for at in ArmorType if at != ArmorType.NONE and am.get_armor(at.name.lower()).can_use(prof)
        }
        assert PROFESSION_WEAPONS[prof] == expected_w, f"Weapon mismatch for {prof}"
        assert PROFESSION_ARMORS[prof] == expected_a, f"Armor mismatch for {prof}"

    # Non-Dawn town (Britain) with 250g spread across members: J pools gold onto Fighter and buys 2H Sword
    party = Party()
    party.add_member(Character("SHADOW", "M", Race.ELF, Profession.THIEF, weapon=WeaponType.SLING, armor=ArmorType.CLOTH, gold=100))
    party.add_member(Character("GRUMM", "M", Race.DWARF, Profession.FIGHTER, weapon=WeaponType.MACE, armor=ArmorType.CLOTH, gold=50))
    party.add_member(Character("SERENA", "F", Race.BOBIT, Profession.CLERIC, weapon=WeaponType.MACE, armor=ArmorType.CLOTH, gold=100))
    party.add_member(Character("ZIRCON", "M", Race.FUZZY, Profession.WIZARD, weapon=WeaponType.DAGGER, armor=ArmorType.CLOTH, gold=0))

    sm = StateMachine(asset_mgr=am, audio=None)
    ts = TownScreen(party=party, asset_mgr=am, map_id=3, start_x=39, start_y=19)
    sm.set_screen(ts)

    ctrl = AutoPlayController(enabled=True)
    for _ in range(80):
        ctrl.step(sm)
        if party.members[1].weapon == WeaponType.SWORD_2H:
            break
    assert party.members[1].weapon == WeaponType.SWORD_2H
    assert sum(m.gold for m in party.members) == 0


def test_lord_british_levels_all_eligible_members_and_exits(pygame_setup):
    """Castle British levels only eligible members (2 & 4 here), skips gated/ineligible ones, and exits."""
    from py_exodus.assets import AssetManager
    from py_exodus.screens.town import TownScreen
    from py_exodus.state_machine import StateMachine

    am = AssetManager("data")
    am.load_all()
    party = _make_party(level=1, exp=0, gold=0)
    party.members[0].level, party.members[0].exp = 2, 120   # already L2, needs 200 for L3
    party.members[1].level, party.members[1].exp = 1, 250   # eligible for L3
    party.members[2].level, party.members[2].exp = 5, 520   # gated at L5 by missing Mark of Kings
    party.members[3].level, party.members[3].exp = 1, 110   # eligible for L2

    sm = StateMachine(asset_mgr=am, audio=None)
    ts = TownScreen(party=party, asset_mgr=am, map_id=1, start_x=32, start_y=15)
    sm.set_screen(ts)

    ctrl = AutoPlayController(enabled=True)
    for _ in range(20):
        ctrl.step(sm)

    assert party.members[0].level == 2
    assert party.members[1].level == 3
    assert party.members[2].level == 5
    assert party.members[3].level == 2
    # Should have left (32, 15) heading toward the exit rather than looping T 1 N
    assert (ts.avatar_x, ts.avatar_y) != (32, 15)


def test_buy_keys_before_ambrosia_and_unlock_locked_door(pygame_setup):
    """Party stocks >= 4 Keys before sailing to Ambrosia and unlocks locked_door tiles with U."""
    from py_exodus.assets import AssetManager
    from py_exodus.autoplay.controller import _GUILD_TOWNS
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.screens.town import TownScreen
    from py_exodus.state_machine import StateMachine

    am = AssetManager("data")
    am.load_all()
    sosaria = load_map(0, am)
    for mid, (px, py, guild_xy) in _GUILD_TOWNS.items():
        assert find_2d_step(sosaria, (46, 20), (px, py), Transport.FOOT) is not None
        tmap = load_map(mid, am)
        assert find_2d_step(tmap, (32, 63), guild_xy, Transport.FOOT) is not None

    party = _make_party(
        level=5, exp=500, marks=[1, 1, 1, 1],
        weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC,
        gold=1500, transport=Transport.FOOT,
    )
    assert evaluate_goal(party) == Goal.BUY_KEYS

    # In Dawn (map 11) at Guild stand (34, 21), buys Keys up to 4
    sm = StateMachine(asset_mgr=am, audio=None)
    ts = TownScreen(party=party, asset_mgr=am, map_id=11, start_x=34, start_y=21)
    sm.set_screen(ts)
    ctrl = AutoPlayController(enabled=True)
    for _ in range(80):
        ctrl.step(sm)
        if sum(m.keys for m in party.members) >= 4:
            break
    assert sum(m.keys for m in party.members) >= 4
    assert evaluate_goal(party) == Goal.CAPTURE_SHIP

    # On Ambrosia (map 13), party at (11, 6) east of locked_door (10, 6) unlocks it with U
    party.map_id = 13
    party.x, party.y = 11, 6
    for m in party.members:
        m.cards = [1, 1, 0, 1]  # missing Moons (6, 6)
    ow = OverworldScreen(party=party, map_id=13, asset_mgr=am, random_encounters=False)
    ow.creatures = []
    sm.set_screen(ow)
    assert ow.game_map.get_tile(10, 6).name == "locked_door"
    keys_before = sum(m.keys for m in party.members)
    for _ in range(10):
        ctrl.step(sm)
        if ow.game_map.get_tile(10, 6).name != "locked_door":
            break
    assert ow.game_map.get_tile(10, 6).name != "locked_door"
    assert sum(m.keys for m in party.members) == keys_before - 1


def test_stats_panel_party_hud_layout(pygame_setup, monkeypatch):
    """StatsPanel shows 3-letter SRC code, omits PARTY/TRANS headers, and places FOOD/GOLD at bottom."""
    from py_exodus.ui.stats_panel import StatsPanel

    party = Party()
    party.add_member(Character("GRUMM", "O", Race.DWARF, Profession.FIGHTER, gold=145, food=592, exp=45))
    captured: list[str] = []

    class _FakeFont:
        def get_linesize(self):
            return 12

        def render(self, text, antialias, color):
            captured.append(text)
            return pygame.Surface((max(1, len(text) * 6), 12))

    fake = _FakeFont()
    panel = StatsPanel(font=fake, small_font=fake)
    surf = pygame.Surface((400, 600))
    panel.render(surf, party, rect=pygame.Rect(0, 0, 300, 500))

    assert any("GRUMM" in s and "ODF" in s and "L:1" in s for s in captured)
    assert any("E:45" in s for s in captured)
    assert not any("PARTY (" in s or "TRANS:" in s for s in captured)
    food_idx = next(i for i, s in enumerate(captured) if "FOOD:" in s and "GOLD:" in s)
    keys_idx = next(i for i, s in enumerate(captured) if "KEYS:" in s and "POWD:" in s)
    member_idx = next(i for i, s in enumerate(captured) if "GRUMM" in s)
    assert member_idx < food_idx < keys_idx


def test_autoplay_syncs_auto_combat_speed(pygame_setup):
    """CombatScreen.auto_combat_interval tracks AutoPlayController.step_interval."""
    from py_exodus.assets import AssetManager

    am = AssetManager("data")
    am.load_all()
    party = _make_party(level=1, exp=0, gold=0)
    cmap = load_conflict_map(37, am)
    sm = StateMachine(asset_mgr=am, audio=None)
    cs = CombatScreen(party=party, combat_map=cmap, asset_mgr=am, monster_count=1)
    sm.set_screen(cs)

    ctrl = AutoPlayController(enabled=True, step_interval=0.01)
    ctrl.step(sm)
    assert cs.auto_combat is True
    assert cs.auto_combat_interval == 0.01


def test_dawn_double_new_moon_wait_and_moongate_helper(pygame_setup):
    """At Dawn (37, 53), passes turns until double new moon before pressing E; moongates wait adjacent."""
    from py_exodus.assets import AssetManager
    from py_exodus.screens.overworld import OverworldScreen

    am = AssetManager("data")
    am.load_all()
    party = _make_party(
        level=5, exp=500, marks=[1, 0, 0, 0],
        weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC,
        gold=60, transport=Transport.FOOT,
    )
    party.x, party.y = 37, 53  # Dawn portal
    party.moon_phase = 5  # Not double new moon
    sm = StateMachine(asset_mgr=am, audio=None)
    ow = OverworldScreen(party=party, asset_mgr=am, random_encounters=False)
    ow.creatures = []
    sm.set_screen(ow)

    ctrl = AutoPlayController(enabled=True)
    # Not double new moon -> passes turn (K_SPACE)
    assert ctrl.step(sm) == pygame.K_SPACE
    # Once double new moon (moon_phase=0), presses K_e to enter Dawn
    party.moon_phase = 0
    assert ctrl.step(sm) == pygame.K_e

    # Moongate wait-and-step helper: adjacent to gate 0, passes when misaligned, steps in when aligned
    gmap = ow.game_map
    gx, gy = gmap.moongates[0].x, gmap.moongates[0].y
    party.moon_phase = 5
    assert ctrl._step_moongate(sm, ow, gmap, party, gx + 1, gy, src_idx=0, dest_idx=0) == pygame.K_SPACE
    party.moon_phase = 0
    assert ctrl._step_moongate(sm, ow, gmap, party, gx + 1, gy, src_idx=0, dest_idx=0) == pygame.K_LEFT


def test_bulk_food_buying_strategy(pygame_setup):
    """When party food < 300 (or member food < 75), Goal.BUY_FOOD buys bulk rations to ~800+."""
    from py_exodus.assets import AssetManager
    from py_exodus.screens.town import TownScreen

    am = AssetManager("data")
    am.load_all()
    party = _make_party(level=1, exp=0, gold=200, food=200)
    for m in party.members:
        m.food = 50
    assert evaluate_goal(party) == Goal.BUY_FOOD

    sm = StateMachine(asset_mgr=am, audio=None)
    ts = TownScreen(party=party, asset_mgr=am, map_id=3, start_x=48, start_y=49)
    sm.set_screen(ts)

    ctrl = AutoPlayController(enabled=True)
    for _ in range(50):
        ctrl.step(sm)
        if party.food >= 800:
            break

    assert party.food >= 700
    assert evaluate_goal(party) != Goal.BUY_FOOD

    # Castle British Food vendor has no counter, so stand (16, 20) is adjacent
    party2 = _make_party(level=1, exp=0, gold=200, food=200)
    for m in party2.members:
        m.food = 50
    ts2 = TownScreen(party=party2, asset_mgr=am, map_id=1, start_x=16, start_y=20)
    sm.set_screen(ts2)
    for _ in range(50):
        ctrl.step(sm)
        if party2.food >= 800:
            break
    assert party2.food >= 700


def test_dungeon_peer_gem_once_per_level_and_touch_mark(pygame_setup):
    """Entering DungeonScreen doesn't crash, peers 1 Gem per unseen level, and touches Marks with S."""
    from py_exodus.assets import AssetManager
    from py_exodus.screens.dungeon_screen import DungeonScreen

    am = AssetManager("data")
    am.load_all()
    party = _make_party(
        level=5, exp=500, marks=[0, 0, 0, 0],
        weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC,
        gold=0, food=500,
    )
    party.members[0].gems = 2
    dmap = load_map(15, am)
    sm = StateMachine(asset_mgr=am, audio=None)
    ds = DungeonScreen(party=party, dungeon_map=dmap, asset_mgr=am)
    ds.state.wandering_creatures = []
    sm.set_screen(ds)

    ctrl = AutoPlayController(enabled=True)
    # First step on (15, 0): peers 1 gem -> gems 2 -> 1, minimap visible
    ctrl.step(sm)
    assert party.members[0].gems == 1
    assert ds.show_minimap is True
    # Subsequent steps on (15, 0) do not consume another gem
    ctrl.step(sm)
    assert party.members[0].gems == 1

    # Place party on MARK_KINGS at (11, 3, 1) -> touches mark for all 4 living members
    ds.state.x, ds.state.y, ds.state.z = 11, 3, 1
    for _ in range(12):
        ctrl.step(sm)
        if all(m.marks[0] > 0 for m in party.members):
            break
    assert all(m.marks[0] > 0 for m in party.members)
    # Only 1 additional gem used for level (15, 1)
    assert party.members[0].gems == 0


def test_dungeon_buys_torches_and_lights_darkness(pygame_setup):
    """Autoplay stocks torches before dungeons and ignites a torch (or casts light) whenever dark."""
    from py_exodus.assets import AssetManager
    from py_exodus.screens.dungeon_screen import DungeonScreen

    am = AssetManager("data")
    am.load_all()
    party = _make_party(
        level=5, exp=500, marks=[0, 0, 0, 0],
        weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC,
        gold=50, food=500,
    )
    party.members[0].gems = 2
    assert evaluate_goal(party) == Goal.BUY_TORCHES

    dmap = load_map(15, am)
    sm = StateMachine(asset_mgr=am, audio=None)
    ds = DungeonScreen(party=party, dungeon_map=dmap, asset_mgr=am)
    ds.state.wandering_creatures = []
    sm.set_screen(ds)

    ctrl = AutoPlayController(enabled=True)
    # With a torch owned and darkness, ignites torch via K_i
    party.members[0].torches = 1
    ds.state.torchtime = 0
    assert ctrl.step(sm) == pygame.K_i
    assert ds.state.is_torch_on is True

    # Out of torches and dark, Wizard casts LORUM via K_c
    party.members[0].torches = 0
    ds.state.torchtime = 0
    party.members[3].mp = 20
    assert ctrl.step(sm) == pygame.K_c


def test_resurrect_dead_member_at_healer(pygame_setup):
    """Dead party member with >= 500g pooled triggers Goal.RESURRECT_DEAD and is revived at Castle British."""
    from py_exodus.assets import AssetManager
    from py_exodus.screens.town import TownScreen

    am = AssetManager("data")
    am.load_all()
    party = _make_party(level=5, exp=500, gold=200, food=500)
    party.members[1].status = Status.DEAD
    party.members[1].hp = 0
    assert evaluate_goal(party) == Goal.RESURRECT_DEAD

    sm = StateMachine(asset_mgr=am, audio=None)
    ts = TownScreen(party=party, asset_mgr=am, map_id=1, start_x=46, start_y=26)
    sm.set_screen(ts)

    ctrl = AutoPlayController(enabled=True)
    for _ in range(30):
        ctrl.step(sm)
        if not party.members[1].is_dead() and not ts.text_log.is_waiting_for_input:
            break

    assert party.members[1].status == Status.GOOD
    assert party.members[1].hp > 0
    assert ts.text_log.is_waiting_for_input is False
    assert evaluate_goal(party) != Goal.RESURRECT_DEAD


def test_cure_poisoned_member_by_spell_or_healer(pygame_setup):
    """Poisoned members are cured on the spot via ALCORT (35 MP) or at a Healer (100g)."""
    from py_exodus.assets import AssetManager
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.screens.town import TownScreen

    am = AssetManager("data")
    am.load_all()
    party = _make_party(level=5, exp=500, gold=50, food=500)
    party.members[1].status = Status.POISONED
    assert evaluate_goal(party) == Goal.CURE_POISON

    # 1. With >= 35 MP on Cleric, casts ALCORT (h) on Overworld immediately
    party.members[2].mp = 35
    party.members[2].max_mp = 50
    sm = StateMachine(asset_mgr=am, audio=None)
    ow = OverworldScreen(party=party, asset_mgr=am, random_encounters=False)
    ow.creatures = []
    sm.set_screen(ow)
    ctrl = AutoPlayController(enabled=True)
    for _ in range(5):
        ctrl.step(sm)
        if party.members[1].status == Status.GOOD:
            break
    assert party.members[1].status == Status.GOOD

    # 2. With < 35 MP and >= 100g, cured at Castle British Healer for 100g
    party.members[1].status = Status.POISONED
    party.members[2].mp = 0
    ts = TownScreen(party=party, asset_mgr=am, map_id=1, start_x=46, start_y=26)
    sm.set_screen(ts)
    for _ in range(25):
        ctrl.step(sm)
        if party.members[1].status == Status.GOOD and not ts.text_log.is_waiting_for_input:
            break
    assert party.members[1].status == Status.GOOD
    assert ts.text_log.is_waiting_for_input is False


def test_stats_panel_autoplay_autocombat_and_turn_count(pygame_setup):
    """StatsPanel renders Autoplay ON/OFF, Autocombat ON/OFF (forced ON when Autoplay ON), and Turn count."""
    from py_exodus.assets import AssetManager
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.ui.stats_panel import StatsPanel

    party = Party(moves=42)
    party.add_member(Character("GRUMM", "O", Race.DWARF, Profession.FIGHTER))
    captured: list[str] = []

    class _FakeFont:
        def get_linesize(self):
            return 12

        def render(self, text, antialias, color):
            captured.append(text)
            return pygame.Surface((max(1, len(text) * 6), 12))

    fake = _FakeFont()
    panel = StatsPanel(font=fake, small_font=fake)
    surf = pygame.Surface((400, 600))

    # 1. Both OFF
    panel.render(surf, party, rect=pygame.Rect(0, 0, 300, 500), autoplay=False, auto_combat=False)
    assert any("AUTOPLAY:" in s and "OFF" in s for s in captured)
    assert any("AUTOCOMBAT:" in s and "OFF" in s for s in captured)
    assert any("TURN: 42" in s for s in captured)

    # 2. Autoplay OFF, Autocombat ON
    captured.clear()
    panel.render(surf, party, rect=pygame.Rect(0, 0, 300, 500), autoplay=False, auto_combat=True)
    assert any("AUTOPLAY:" in s and "OFF" in s for s in captured)
    assert any("AUTOCOMBAT:" in s and "ON" in s for s in captured)

    # 3. Autoplay ON always forces Autocombat ON
    captured.clear()
    panel.render(surf, party, rect=pygame.Rect(0, 0, 300, 500), autoplay=True, auto_combat=False)
    assert any("AUTOPLAY:" in s and "ON" in s for s in captured)
    assert any("AUTOCOMBAT:" in s and "ON" in s for s in captured)

    # 4. Screen integration via StateMachine + OverworldScreen
    am = AssetManager("data")
    am.load_all()
    sm = StateMachine(asset_mgr=am, audio=None)
    ow = OverworldScreen(party=party, asset_mgr=am, random_encounters=False)
    ow.stats_panel = panel
    sm.set_screen(ow)
    sm.autoplay_enabled = True
    sm.autoplay_step_interval = 0.05
    party.transport = Transport.SHIP
    party.ship_hull = 38
    party.members[0].gold = 77
    party.members[0].marks[0] = 1
    captured.clear()
    ow._render_stats_panel(surf, pygame.Rect(0, 0, 300, 500))
    assert any("AUTOPLAY:" in s and "ON (0.05s)" in s for s in captured)
    assert any("AUTOCOMBAT:" in s and "ON" in s for s in captured)
    assert any("TURN: 42" in s for s in captured)
    assert any("G:77" in s for s in captured)
    assert any("TOR:" in s for s in captured)
    assert any("SHIP HULL: 38/50" in s for s in captured)
    assert any("MARKS: K:1 F:0 S:0 O:0" in s for s in captured)
    assert any("CARDS: L:0 S:0 M:0 D:0" in s for s in captured)
    assert any("EXOTICS: W:0/4 A:0/4" in s for s in captured)
    assert any("LOC: Sosaria" in s for s in captured)
    assert any("GOAL:" in s for s in captured)


def test_heal_rest_on_sosaria_and_walkable_coast_patrol(pygame_setup):
    """Hurt parties with a living healer rest on Sosaria for MP instead of fighting, and coast patrol tiles are walkable."""
    from py_exodus.assets import AssetManager
    from py_exodus.autoplay.nav import find_2d_step
    from py_exodus.screens.overworld import OverworldScreen

    am = AssetManager("data")
    am.load_all()
    party = _make_party(level=3, exp=200, gold=100, food=300)
    party.members[0].hp = 100
    party.members[0].max_hp = 350
    party.members[2].mp = 0
    party.members[2].max_mp = 25

    sm = StateMachine(asset_mgr=am, audio=None, party=party)
    ow = OverworldScreen(party=party, asset_mgr=am, random_encounters=False)
    ow.creatures = [{"x": 45, "y": 20, "tile_name": "orc"}]
    sm.set_screen(ow)

    ctrl = AutoPlayController(enabled=True)
    # Hurt party with living Cleric at 0 MP evades adjacent monster, then rests with K_SPACE when safe
    assert ctrl.step(sm) in (pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT)
    ow.creatures = []
    assert ctrl.step(sm) == pygame.K_SPACE

    # Coast patrol points for CAPTURE_SHIP must all be reachable on foot from Dardin's Pit (46, 7)
    for coord in [(45, 12), (45, 14), (44, 16), (44, 14)]:
        assert find_2d_step(ow.game_map, (46, 7), {coord}, Transport.FOOT) is not None


def test_mark_kings_triggers_on_first_level5_and_resurrection_reserve():
    """First member hitting L5 triggers GET_MARK_KINGS, and L5+ keeps 500g resurrection reserve."""
    from py_exodus.autoplay.equipment import best_shop_upgrade

    # Mixed levels: only member 0 is L5, others L3 -> stays in GRIND_AND_LEVEL until all living are L5+
    party = _make_party(level=3, exp=200, gold=0, food=500, marks=[0, 0, 0, 0])
    party.members[0].level = 5
    party.members[0].exp = 450
    assert evaluate_goal(party) == Goal.GRIND_AND_LEVEL
    for m in party.members:
        m.level = 5
        m.exp = 450
    assert evaluate_goal(party) == Goal.GET_MARK_KINGS

    # At L5+ with mid gear, 600g pooled reserves 500g so 400g Dawn Axe+2 is not bought yet
    for m in party.members:
        if m.profession in (Profession.FIGHTER, Profession.RANGER):
            m.weapon = WeaponType.AXE
        m.armor = ArmorType.LEATHER
    party.members[0].gold = 600
    up_600 = best_shop_upgrade(party)
    assert up_600 is None or up_600.price <= 100

    # With 950g pooled (450g above 500g reserve), 350g-400g upgrades ARE bought
    party.members[0].gold = 950
    up_950 = best_shop_upgrade(party)
    assert up_950 is not None and 100 < up_950.price <= 450

    # If a member is dead when someone is L5, resurrect before Mark of Kings
    # (even when the dead member holds the pooled gold!); and if a dead member
    # cannot be revived yet (<500g) while living members are poisoned (>=100g),
    # cure poison before grinding.
    party.members[0].gold = 0
    party.members[1].gold = 1200
    party.members[1].status = Status.DEAD
    party.members[1].hp = 0
    assert evaluate_goal(party) == Goal.RESURRECT_DEAD
    party.members[1].gold = 200
    party.members[2].status = Status.POISONED
    assert evaluate_goal(party) == Goal.CURE_POISON
    party.members[2].status = Status.GOOD
    party.members[1].status = Status.GOOD
    party.members[1].hp = 150
    party.members[0].marks[0] = 1
    party.members[1].gold = 0
    assert evaluate_goal(party) == Goal.GET_MARK_KINGS


def test_autoplay_stops_on_game_over_and_evades_sea_monsters_early(pygame_setup):
    """Autoplay stops on StartScreen(game_over=True) instead of restarting, and L1 parties evade coastal serpents."""
    from py_exodus.assets import AssetManager
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.screens.start import StartScreen

    am = AssetManager("data")
    am.load_all()
    sm = StateMachine(asset_mgr=am, audio=None)
    ss = StartScreen(asset_mgr=am, game_over=True)
    sm.set_screen(ss)
    ctrl = AutoPlayController(enabled=True)
    assert ctrl.step(sm) is None
    assert ctrl.enabled is False
    assert sm.autoplay_enabled is False

    # L1 party on coast steps away from adjacent serpent instead of fighting it
    party = _make_party(level=1, exp=0, gold=0, food=500)
    ow = OverworldScreen(party=party, asset_mgr=am, random_encounters=False, start_x=47, start_y=19)
    ow.creatures = [{"x": 48, "y": 19, "tile_name": "serpent"}]
    sm.set_screen(ow)
    ctrl.enabled = True
    assert ctrl.step(sm) in (pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT)

    # Starving party in BUY_FOOD does not loop casting SANCTU instead of walking to buy food
    party.food = 0
    party.members[0].hp = 50
    party.members[0].max_hp = 150
    party.members[0].gold = 100
    party.members[2].mp = 25
    party.members[2].max_mp = 25
    ow.creatures = []
    assert evaluate_goal(party) == Goal.BUY_FOOD
    assert ctrl.step(sm) != pygame.K_c

    # When party dies during autoplay, check_party_death freezes on current screen & logs turn
    for m in party.members:
        m.status = Status.DEAD
        m.hp = 0
    party.moves = 321
    sm.autoplay_enabled = True
    assert ow.check_party_death() is True
    assert sm.current_screen is ow
    assert sm.autoplay_enabled is False
    assert any("PARTY DEAD on turn 321" in msg for msg in ow.text_log.lines)

    # Empty party on RosterScreen must NOT stop autoplay (is_party_dead is True when empty)
    from py_exodus.screens.roster_screen import RosterScreen

    empty_party = Party()
    rs = RosterScreen(party=empty_party, asset_mgr=am)
    sm.set_screen(rs)
    ctrl.enabled = True
    assert ctrl.step(sm) is not None
    assert ctrl.enabled is True

    # L1 party on foot near coast must not spawn sea monsters (serpent/pirate)
    ow_l1 = OverworldScreen(party=_make_party(level=1, exp=0), asset_mgr=am, random_encounters=True, start_x=46, start_y=19)
    ow_l1.creatures.clear()
    for _ in range(40):
        ow_l1._spawn_wandering_creature()
    assert not any(c.get("tile_name") in ("serpent", "pirate", "squid") for c in ow_l1.creatures)

    # Out-of-combat SANCTU targets the most injured member, not member 1 at 540/550
    p_heal = _make_party(level=5, exp=500, gold=0, food=500)
    p_heal.members[0].hp = 540
    p_heal.members[0].max_hp = 550
    p_heal.members[3].hp = 50
    p_heal.members[3].max_hp = 350
    p_heal.members[2].mp = 20
    p_heal.members[2].max_mp = 50
    ow_h = OverworldScreen(party=p_heal, asset_mgr=am, random_encounters=False)
    ow_h.creatures = []
    sm.set_screen(ow_h)
    ctrl.enabled = True
    for _ in range(5):
        ctrl.step(sm)
    assert p_heal.members[3].hp > 50
    assert p_heal.members[0].hp == 540

    # Sailing ship fires cannons (K_f) at aligned broadsides serpent and steers around non-aligned serpents
    p_ship = _make_party(level=5, exp=500, gold=1500, food=500, marks=[1, 1, 1, 1], transport=Transport.SHIP)
    p_ship.members[0].keys = 4
    for m in p_ship.members:
        m.weapon = WeaponType.EXOTIC
        m.weapons[WeaponType.EXOTIC] = 1
        m.armor = ArmorType.EXOTIC
        m.armors[ArmorType.EXOTIC] = 1
    p_ship.x, p_ship.y = 52, 15
    ow_s = OverworldScreen(party=p_ship, asset_mgr=am, random_encounters=False)
    ow_s.heading = Direction.NORTH
    ow_s.creatures = [{"x": 54, "y": 15, "tile_name": "serpent"}]
    sm.set_screen(ow_s)
    ctrl._key_queue.clear()
    assert evaluate_goal(p_ship) == Goal.SAIL_WHIRLPOOL
    assert ctrl.step(sm) == pygame.K_f
    assert ctrl.step(sm) == pygame.K_RIGHT

    # SAIL_WHIRLPOOL tracks live whirlpool creature coordinates, not just static (50, 13)
    p_ship.wind_direction = Direction.EAST
    ow_s.creatures = [{"x": 52, "y": 17, "tile_name": "whirlpool"}]
    assert ctrl.step(sm) == pygame.K_DOWN

    # Ranged bows beat Exotic while prefer_ranged=True; Wizard/Cleric equip Exotic immediately; CONQUER_EXODUS switches to Exotic
    from py_exodus.autoplay.equipment import best_owned_weapon

    fighter = Character("F", "M", Race.HUMAN, Profession.FIGHTER)
    fighter.weapon = WeaponType.BOW
    fighter.weapons[WeaponType.BOW] = 1
    fighter.weapons[WeaponType.EXOTIC] = 1
    assert best_owned_weapon(fighter, prefer_ranged=True) is None
    assert best_owned_weapon(fighter, prefer_ranged=False) == WeaponType.EXOTIC

    wiz = Character("W", "M", Race.FUZZY, Profession.WIZARD)
    wiz.weapon = WeaponType.DAGGER
    wiz.weapons[WeaponType.DAGGER] = 1
    wiz.weapons[WeaponType.EXOTIC] = 1
    assert best_owned_weapon(wiz, prefer_ranged=True) == WeaponType.EXOTIC

    # Gate 1 (57, 46) picks reachable Gate 3 instead of impossible dest_idx=0
    assert ctrl._pick_moongate_dest(ow_s.game_map, 1, (45, 18), p_ship) == 3

    # Disembarking onto exotic island (34, 3) stays in DIG_EXOTICS instead of looping K_x <-> K_b
    p_ex = _make_party(level=5, exp=500, gold=100, food=250, marks=[1, 0, 0, 0], transport=Transport.FOOT)
    p_ex.x, p_ex.y = 34, 3
    p_ex.dynamic_objects.append({"tile": "frigate", "x": 34, "y": 3})
    ow_ex = OverworldScreen(party=p_ex, asset_mgr=am, random_encounters=False)
    sm.set_screen(ow_ex)
    ctrl._key_queue.clear()
    assert evaluate_goal(p_ex) == Goal.DIG_EXOTICS
    assert ctrl.step(sm) == pygame.K_LEFT
    # Also stays in DIG_EXOTICS with a dead member & 800g instead of looping RESURRECT_DEAD <-> DIG_EXOTICS
    p_ex.members[3].status = Status.DEAD
    p_ex.members[3].hp = 0
    p_ex.members[0].gold = 800
    assert evaluate_goal(p_ex) == Goal.DIG_EXOTICS

    # Ship in DIG_EXOTICS steers around whirlpool instead of sailing into it
    p_whirl = _make_party(level=3, exp=200, gold=0, food=500, transport=Transport.SHIP)
    p_whirl.x, p_whirl.y = 49, 13
    p_whirl.wind_direction = Direction.NORTH
    ow_w = OverworldScreen(party=p_whirl, asset_mgr=am, random_encounters=False)
    ow_w.creatures = [{"x": 50, "y": 13, "tile_name": "whirlpool"}]
    sm.set_screen(ow_w)
    ctrl._key_queue.clear()
    assert ctrl.step(sm) != pygame.K_RIGHT

    # On SOL island (45, 52) in EXIT_AMBROSIA, heads toward parked frigate (43, 58) instead of vantage_tiles
    p_amb = _make_party(level=5, exp=500, gold=100, food=500, marks=[1, 0, 0, 0], cards=[1, 1, 1, 1])
    p_amb.x, p_amb.y = 45, 52
    p_amb.dynamic_objects.append({"tile": "frigate", "x": 43, "y": 58})
    ow_amb = OverworldScreen(party=p_amb, asset_mgr=am, random_encounters=False, map_id=13)
    sm.set_screen(ow_amb)
    ctrl._key_queue.clear()
    step_amb = ctrl.step(sm)
    assert step_amb in (pygame.K_DOWN, pygame.K_LEFT)

    # Ship returning to mainland in GRIND_AND_LEVEL targets water tiles adjacent to mainland, not land
    p_ret = _make_party(level=3, exp=200, gold=0, food=500, transport=Transport.SHIP)
    for m in p_ret.members:
        m.weapon = WeaponType.EXOTIC
        m.weapons[WeaponType.EXOTIC] = 1
        m.armor = ArmorType.EXOTIC
        m.armors[ArmorType.EXOTIC] = 1
    p_ret.x, p_ret.y = 18, 44
    p_ret.wind_direction = Direction.EAST
    ow_r = OverworldScreen(party=p_ret, asset_mgr=am, random_encounters=False)
    ow_r.creatures = []
    sm.set_screen(ow_r)
    ctrl._key_queue.clear()
    assert evaluate_goal(p_ret) == Goal.GRIND_AND_LEVEL
    assert ctrl.step(sm) != pygame.K_SPACE

    # Hurt party on SHIP with 0-MP living healer rests (K_SPACE) to regen MP instead of sailing into battle
    p_ret.members[0].hp = 50
    p_ret.members[0].max_hp = 450
    p_ret.members[2].mp = 0
    p_ret.members[2].max_mp = 50
    assert ctrl.step(sm) == pygame.K_SPACE

    # CAPTURE_SHIP loots dropped chests instead of ignoring them
    p_cap2 = _make_party(level=5, exp=500, gold=1500, food=500, marks=[1, 1, 1, 1], weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC, transport=Transport.FOOT)
    p_cap2.members[0].keys = 4
    p_cap2.x, p_cap2.y = 44, 15
    p_cap2.dynamic_objects.append({"tile": "chest", "x": 44, "y": 16})
    ow_c2 = OverworldScreen(party=p_cap2, asset_mgr=am, random_encounters=False)
    sm.set_screen(ow_c2)
    ctrl._key_queue.clear()
    assert evaluate_goal(p_cap2) == Goal.CAPTURE_SHIP
    assert ctrl.step(sm) == pygame.K_DOWN

    # Broadsides do not fire across non-wrapping map borders (e.g. x=1 -> x=63)
    p_edge = _make_party(level=5, exp=500, gold=0, food=500, marks=[1, 0, 0, 0], transport=Transport.SHIP)
    for m in p_edge.members:
        m.weapon = WeaponType.EXOTIC
        m.weapons[WeaponType.EXOTIC] = 1
        m.armor = ArmorType.EXOTIC
        m.armors[ArmorType.EXOTIC] = 1
    p_edge.x, p_edge.y = 1, 37
    ow_ed = OverworldScreen(party=p_edge, asset_mgr=am, random_encounters=False)
    ow_ed.heading = Direction.NORTH
    ow_ed.creatures = [{"x": 63, "y": 37, "tile_name": "serpent"}]
    sm.set_screen(ow_ed)
    ctrl._key_queue.clear()
    assert ctrl.step(sm) != pygame.K_f

    # Ship in DIG_EXOTICS avoids pirate broadside lane at distance 3 (steps perpendicular out of lane)
    p_lane = _make_party(level=5, exp=500, gold=0, food=500, marks=[1, 0, 0, 0], transport=Transport.SHIP)
    p_lane.x, p_lane.y = 52, 15
    p_lane.wind_direction = Direction.NORTH
    ow_pl = OverworldScreen(party=p_lane, asset_mgr=am, random_encounters=False)
    ow_pl.heading = Direction.EAST
    ow_pl.creatures = [{"x": 55, "y": 15, "tile_name": "pirate"}]  # 3 tiles East in broadside lane
    sm.set_screen(ow_pl)
    ctrl._key_queue.clear()
    assert ctrl.step(sm) != pygame.K_RIGHT

    # On SOL island (45, 52) in EXIT_AMBROSIA, heads toward parked frigate (43, 58) instead of vantage_tiles
    p_amb = _make_party(level=5, exp=500, gold=100, food=500, marks=[1, 0, 0, 0], cards=[1, 1, 1, 1])
    p_amb.x, p_amb.y = 45, 52
    p_amb.dynamic_objects.append({"tile": "frigate", "x": 43, "y": 58})
    ow_amb = OverworldScreen(party=p_amb, asset_mgr=am, random_encounters=False, map_id=13)
    sm.set_screen(ow_amb)
    ctrl._key_queue.clear()
    step_amb = ctrl.step(sm)
    assert step_amb in (pygame.K_DOWN, pygame.K_LEFT)

    # Missing Death/Moons card with 0 keys & <50g stays in GRIND_AND_LEVEL instead of looping SAIL_WHIRLPOOL <-> EXIT_AMBROSIA
    p_nokey = _make_party(level=5, exp=500, gold=10, food=500, marks=[1, 1, 1, 1], transport=Transport.FOOT)
    for m in p_nokey.members:
        m.weapon = WeaponType.EXOTIC
        m.weapons[WeaponType.EXOTIC] = 1
        m.armor = ArmorType.EXOTIC
        m.armors[ArmorType.EXOTIC] = 1
        m.keys = 0
    assert evaluate_goal(p_nokey) == Goal.GRIND_AND_LEVEL

    # Stranded on island for BUY_FOOD uses reachable moongate or frigate instead of passing turns
    p_isl = _make_party(level=5, exp=500, gold=100, food=50)
    p_isl.food = 50
    p_isl.x, p_isl.y = 58, 44  # Snake Island, unreachable on foot from Britain
    ow_i = OverworldScreen(party=p_isl, asset_mgr=am, random_encounters=False)
    ow_i.creatures = []
    sm.set_screen(ow_i)
    assert evaluate_goal(p_isl) == Goal.BUY_FOOD
    # With a frigate parked nearby on the coast, boards or walks toward it instead of K_SPACE
    p_isl.dynamic_objects.append({"tile": "frigate", "x": 58, "y": 44})
    assert ctrl.step(sm) == pygame.K_b

    # BUY_FOOD picks Yew (34, 16) when closer than Britain, and skips closed Dawn
    p_yew = _make_party(level=5, exp=500, gold=100, food=50)
    p_yew.food = 50
    p_yew.x, p_yew.y = 33, 16
    ow_y = OverworldScreen(party=p_yew, asset_mgr=am, random_encounters=False)
    ow_y.creatures = []
    sm.set_screen(ow_y)
    assert ctrl.step(sm) == pygame.K_RIGHT  # toward Yew (34, 16)

    # CAPTURE_SHIP ignores unreachable open-ocean frigates and keeps patrolling coast
    p_cap = _make_party(level=5, exp=500, gold=1500, food=500, marks=[1, 1, 1, 1], weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC)
    p_cap.members[0].keys = 4
    p_cap.x, p_cap.y = 45, 12
    p_cap.dynamic_objects.append({"tile": "frigate", "x": 55, "y": 12})  # unreachable in deep water
    ow_c = OverworldScreen(party=p_cap, asset_mgr=am, random_encounters=False)
    ow_c.creatures = []
    sm.set_screen(ow_c)
    assert evaluate_goal(p_cap) == Goal.CAPTURE_SHIP
    assert ctrl.step(sm) != pygame.K_SPACE


def test_wind_hold_four_heading_progress_and_hull_triage_policy(pygame_setup):
    """4-heading sea legs advance along allowed wind-free steps and hold only at blocked turns; hull <= 25 shares one policy."""
    from py_exodus.assets import AssetManager
    from py_exodus.screens.overworld import OverworldScreen

    am = AssetManager("data")
    am.load_all()
    ctrl = AutoPlayController(enabled=True)
    sm = StateMachine(asset_mgr=am, audio=None)

    # 1. Wind-hold 4-heading leg: ship near (32, 58) heading to armor island berth (34, 3).
    # Even when wind blocks a later heading (e.g. SOUTH blocks NORTH), ship advances when free_d != wind.reverse()
    # instead of holding forever until food < 100, and holds (K_SPACE) when free_d IS blocked.
    p = _make_party(level=5, exp=500, gold=500, food=500, marks=[1, 0, 0, 0], transport=Transport.SHIP)
    p.x, p.y = 32, 59
    p.wind_direction = Direction.SOUTH  # blocks NORTH, allows SOUTH/WEST/EAST
    ow = OverworldScreen(party=p, asset_mgr=am, random_encounters=False)
    ow.creatures = []
    sm.set_screen(ow)

    steps_moved = 0
    for _ in range(25):
        key = ctrl.step(sm)
        if key != pygame.K_SPACE:
            steps_moved += 1
        if (p.x, p.y) == (34, 3):
            break
    assert steps_moved > 0  # made forward progress while food >= 100

    # When wind directly opposes free_d (SOUTH from (34, 59) toward (34, 3)) and forces >1.5x detour, holds with K_SPACE
    ctrl._key_queue.clear()
    p2 = _make_party(level=5, exp=500, gold=500, food=500, marks=[1, 0, 0, 0], transport=Transport.SHIP)
    p2.x, p2.y = 34, 59
    p2.wind_direction = Direction.NORTH  # blocks SOUTH (direct wrapped route to (34, 3))
    ow2 = OverworldScreen(party=p2, asset_mgr=am, random_encounters=False)
    ow2.creatures = []
    sm.set_screen(ow2)
    assert ctrl.step(sm) == pygame.K_SPACE

    # 2. Unified hull triage policy (<= 25): skips broadsides, disembarks adjacent to land, skips last_ship
    p_hull = _make_party(level=5, exp=500, gold=500, food=500, marks=[1, 0, 0, 0], transport=Transport.SHIP)
    p_hull.ship_hull = 25
    p_hull.x, p_hull.y = 34, 3  # adjacent to (33, 3) land
    ow_h = OverworldScreen(party=p_hull, asset_mgr=am, random_encounters=False)
    ow_h.creatures = [{"x": 34, "y": 5, "tile_name": "pirate"}]  # in broadside range
    sm.set_screen(ow_h)
    assert ctrl._is_hull_critical(p_hull, ow_h) is True
    assert ctrl.step(sm) == pygame.K_x  # disembarks instead of firing broadsides

    last = {"tile": "frigate", "x": 34, "y": 3}
    p_hull.ship_hull = 25
    p_hull.last_ship = last
    p_hull.dynamic_objects = [last]
    assert (34, 3) not in ctrl._boardable_frigates(p_hull)


def test_rest_guard_stack_and_broke_starving_trigger(pygame_setup):
    """Rest-guard stack aborts without oscillation; broke_and_starving fights land foes only when no naval threat is near."""
    from py_exodus.assets import AssetManager
    from py_exodus.screens.overworld import OverworldScreen

    am = AssetManager("data")
    am.load_all()
    ctrl = AutoPlayController(enabled=True)
    sm = StateMachine(asset_mgr=am, audio=None)

    # 1. Rest-guard stack: taking damage on a tile aborts K_SPACE rest and avoids oscillating back
    p = _make_party(level=5, exp=500, gold=500, food=500, marks=[1, 0, 0, 0])
    p.members[0].hp = 50
    p.members[0].max_hp = 450
    p.members[2].mp = 0
    p.members[2].max_mp = 50
    p.x, p.y = 40, 20
    ow = OverworldScreen(party=p, asset_mgr=am, random_encounters=False)
    ow.creatures = []
    sm.set_screen(ow)

    # First rest establishes _prev_ow_hp_state
    assert ctrl.step(sm) == pygame.K_SPACE
    # Simulate taking ranged/ambient damage while resting at (40, 20)
    p.members[0].hp = 35
    assert ctrl.step(sm) != pygame.K_SPACE  # took_hit_here aborts rest

    # Starving (food == 0) also skips K_SPACE rest
    p.members[0].food = 0
    ctrl._prev_ow_hp_state = None
    assert ctrl.step(sm) != pygame.K_SPACE

    # 2. broke_and_starving: gold < 30, food == 0, HP >= 30% chases nearby land creature...
    p_bs = _make_party(level=5, exp=500, gold=0, food=0, marks=[1, 0, 0, 0])
    for m in p_bs.members:
        m.food = 0
        m.mp = 0  # prevent Sanctu cast before movement check
        m.hp = int(m.max_hp * 0.6)  # hurt (<85% needs_heal), but >= 30%
    p_bs.x, p_bs.y = 40, 20
    ow_bs = OverworldScreen(party=p_bs, asset_mgr=am, random_encounters=False)
    ow_bs.creatures = [{"x": 40, "y": 19, "tile_name": "orc"}]
    sm.set_screen(ow_bs)
    assert ctrl.step(sm) == pygame.K_UP  # chases orc to earn 30g for food

    # ...but never while a pirate or sea serpent is near (<= 7 tiles)
    ow_bs.creatures.append({"x": 40, "y": 23, "tile_name": "pirate"})
    assert ctrl.step(sm) != pygame.K_UP

    # 3. Stranded on Snake Island (57, 46) in GRIND_AND_LEVEL uses moongate/frigate instead of K_SPACE stall
    p_snk = _make_party(
        level=8, exp=1500, gold=200, food=500, marks=[1, 1, 1, 1],
        weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC,
    )
    p_snk.members[0].keys = 4
    p_snk.x, p_snk.y = 57, 46
    ow_snk = OverworldScreen(party=p_snk, asset_mgr=am, random_encounters=False)
    ow_snk.creatures = []
    sm.set_screen(ow_snk)
    assert evaluate_goal(p_snk) == Goal.GRIND_AND_LEVEL
    assert ctrl.step(sm) != pygame.K_SPACE

    # 4. Town exit in Britain uses nearest border (east gate) instead of walking south along the east edge
    from py_exodus.screens.town import TownScreen

    p_br = _make_party(level=1, exp=0, gold=0, food=500)
    ts_br = TownScreen(party=p_br, asset_mgr=am, map_id=3, start_x=63, start_y=32)
    sm.set_screen(ts_br)
    assert ctrl.step(sm) == pygame.K_RIGHT

    # 5. Disembarking in GET_REMAINING_MARKS onto Snake Island shore walks toward dungeon instead of B/X looping
    p_rem = _make_party(
        level=9, exp=2000, gold=500, food=500, marks=[1, 1, 0, 1],
        weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC, transport=Transport.FOOT,
    )
    p_rem.members[0].gems = 8
    p_rem.members[0].torches = 4
    p_rem.x, p_rem.y = 60, 46  # shore water tile east of Snake Island (58, 44)
    p_rem.dynamic_objects.append({"tile": "frigate", "x": 60, "y": 46})
    ow_rem = OverworldScreen(party=p_rem, asset_mgr=am, random_encounters=False)
    ow_rem.creatures = []
    sm.set_screen(ow_rem)
    assert evaluate_goal(p_rem) == Goal.GET_REMAINING_MARKS
    assert ctrl.step(sm) != pygame.K_b  # walks west onto grass toward (58, 44) instead of re-boarding

    # 6. Single low-food member triggers BUY_FOOD on SHIP and EXIT_AMBROSIA in Ambrosia even if party.food >= 250
    p_ship_food = _make_party(
        level=10, exp=3000, gold=1500, food=500, marks=[1, 1, 1, 1],
        weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC, transport=Transport.SHIP,
    )
    p_ship_food.members[0].food = 35
    p_ship_food.members[1].food = 900
    assert evaluate_goal(p_ship_food, map_id=0) == Goal.BUY_FOOD
    assert evaluate_goal(p_ship_food, map_id=13) == Goal.EXIT_AMBROSIA

    # 7. Uneven food [65, 615, 51, 91] equalizes all <400 members strictly lowest-first to >=400, leaving 615 untouched
    p_eq = _make_party(level=10, exp=3000, gold=1000, food=500)
    for m, f_val in zip(p_eq.members, (65, 615, 51, 91)):
        m.food = f_val
    ts_eq = TownScreen(party=p_eq, asset_mgr=am, map_id=3, start_x=48, start_y=49)
    sm.set_screen(ts_eq)
    ctrl._key_queue.clear()
    for _ in range(100):
        ctrl.step(sm)
        if sm.current_screen is not ts_eq:
            break
    assert min(m.food for m in p_eq.members) >= 400
    assert max(m.food for m in p_eq.members) == 615

    # 8. Dead member holding gold still counts toward party.gold for BUY_FOOD (poolable via J)
    p_dead_g = _make_party(level=5, exp=500, gold=0, food=0)
    for m in p_dead_g.members:
        m.food = 0
    p_dead_g.members[0].status = Status.DEAD
    p_dead_g.members[0].hp = 0
    p_dead_g.members[0].gold = 200
    assert evaluate_goal(p_dead_g, map_id=0) == Goal.BUY_FOOD

    # 9. Ambrosia (35, 9) with pirate in bay waits at best_shore without oscillating, and update() caps steps/frame
    p_amb_bay = _make_party(
        level=14, exp=3000, gold=780, food=257, marks=[1, 1, 1, 1], cards=[1, 1, 0, 1],
        weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC,
    )
    p_amb_bay.members[0].keys = 18
    p_amb_bay.x, p_amb_bay.y = 35, 9
    ow_bay = OverworldScreen(party=p_amb_bay, map_id=13, asset_mgr=am, random_encounters=False)
    ow_bay.creatures = [{"x": 34, "y": 10, "tile_name": "pirate"}]
    sm.set_screen(ow_bay)
    ctrl._key_queue.clear()
    assert ctrl.step(sm) == pygame.K_SPACE

    ctrl.step_interval = 0.01
    ctrl._timer = 0.0
    ctrl.update(1.0, sm)  # large dt backlog is capped so event loop never freezes
    assert ctrl._timer < ctrl.step_interval

    # 10. at_exotic_island only suppresses dead-member grind while on FOOT, not when sailing past on SHIP
    p_ex_ship = _make_party(level=13, exp=3000, gold=100, food=500, marks=[1, 0, 0, 0], transport=Transport.SHIP)
    p_ex_ship.members[3].status = Status.DEAD
    p_ex_ship.members[3].hp = 0
    p_ex_ship.x, p_ex_ship.y = 20, 44
    assert evaluate_goal(p_ex_ship, map_id=0) == Goal.GRIND_AND_LEVEL
    p_ex_ship.transport = Transport.FOOT
    p_ex_ship.x, p_ex_ship.y = 19, 44
    assert evaluate_goal(p_ex_ship, map_id=0) == Goal.DIG_EXOTICS

    # 11. GRIND_AND_LEVEL on SHIP at non-mainland (18, 42) sails to mainland instead of K_SPACE stalling
    p_1842 = _make_party(level=6, exp=600, gold=100, food=500, marks=[1, 0, 0, 0], transport=Transport.SHIP)
    p_1842.members[3].status = Status.DEAD
    p_1842.members[3].hp = 0
    p_1842.x, p_1842.y = 18, 42
    p_1842.wind_direction = Direction.EAST
    ow_1842 = OverworldScreen(party=p_1842, asset_mgr=am, random_encounters=False)
    ow_1842.creatures = []
    sm.set_screen(ow_1842)
    ctrl._key_queue.clear()
    assert evaluate_goal(p_1842, map_id=0) == Goal.GRIND_AND_LEVEL
    assert ctrl.step(sm) != pygame.K_SPACE

    # 12. CONQUER_EXODUS with EXOTIC equipped and BOW in inventory stays CONQUER_EXODUS (no OUTFIT_BRITAIN flip)
    p_exodus = _make_party(
        level=25, exp=2400, gold=2000, food=500, marks=[1, 1, 1, 1], cards=[1, 1, 1, 1],
        weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC,
    )
    p_exodus.members[0].weapons[WeaponType.BOW] = 1
    p_exodus.members[1].weapons[WeaponType.BOW_P2] = 1
    assert evaluate_goal(p_exodus, map_id=0) == Goal.CONQUER_EXODUS

    # 13. Pre-Ambrosia gold target raises to 4500 when stats below cap; Death Gulch & Shrine stat-leveling
    p_dg = _make_party(
        level=10, exp=1000, gold=500, food=500, marks=[1, 1, 1, 1],
        weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC,
    )
    p_dg.members[0].keys = 4
    assert evaluate_goal(p_dg, map_id=0) == Goal.GRIND_AND_LEVEL
    ts_dg = TownScreen(party=p_dg, asset_mgr=am, map_id=10, start_x=13, start_y=8)
    sm.set_screen(ts_dg)
    ctrl._key_queue.clear()
    k_dg = ctrl.step(sm)
    assert k_dg in (pygame.K_c, pygame.K_g)  # opens chest on (13, 8)

    # Ambrosia with 4 cards and 2000g stays in AMBROSIA_CARDS_SHRINES to upgrade stats
    p_shr = _make_party(
        level=15, exp=1500, gold=500, food=500, marks=[1, 1, 1, 1], cards=[1, 1, 1, 1],
        weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC,
    )
    assert evaluate_goal(p_shr, map_id=13) == Goal.AMBROSIA_CARDS_SHRINES
    ow_shr = OverworldScreen(party=p_shr, map_id=13, asset_mgr=am, random_encounters=False)
    p_shr.x, p_shr.y = 55, 27  # Wisdom Shrine (Cleric prioritized first)
    sm.set_screen(ow_shr)
    ctrl._key_queue.clear()
    assert ctrl.step(sm) == pygame.K_e  # enters ShrineScreen

    # Death Gulch sailing from mainland coast (46, 18) must not Board/Xit loop under Wind CALM
    p_sail = _make_party(
        level=10, exp=950, gold=110, food=200, marks=[1, 1, 1, 1],
        weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC,
    )
    p_sail.members[0].keys = 5
    p_sail.x, p_sail.y = 46, 18
    p_sail.wind_direction = None
    p_sail.dynamic_objects = [{"tile": "frigate", "x": 46, "y": 18}]
    ow_sail = OverworldScreen(party=p_sail, map_id=0, asset_mgr=am, random_encounters=False)
    sm.set_screen(ow_sail)
    ctrl._key_queue.clear()
    assert ctrl.step(sm) == pygame.K_b
    assert p_sail.transport == Transport.SHIP
    p_sail.wind_direction = None
    assert ctrl.step(sm) == pygame.K_SPACE
    assert p_sail.transport == Transport.SHIP

    # Disembarking at Death Gulch's shore (54, 32) must walk onto (55, 32), not B/X loop back to Britain
    p_dg_shore = _make_party(
        level=10, exp=950, gold=110, food=200, marks=[1, 1, 1, 1],
        weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC,
    )
    p_dg_shore.members[0].keys = 5
    p_dg_shore.x, p_dg_shore.y = 54, 32
    p_dg_shore.transport = Transport.SHIP
    p_dg_shore.dynamic_objects = [{"tile": "frigate", "x": 54, "y": 32}]
    ow_dg_shore = OverworldScreen(party=p_dg_shore, map_id=0, asset_mgr=am, random_encounters=False)
    sm.set_screen(ow_dg_shore)
    ctrl._key_queue.clear()
    assert ctrl.step(sm) == pygame.K_x
    assert p_dg_shore.transport == Transport.FOOT
    assert ctrl.step(sm) == pygame.K_RIGHT
    assert (p_dg_shore.x, p_dg_shore.y) == (55, 32)

    # Poisoned member + Cleric with 15/50 MP in Death Gulch must NOT spam SANCTU (saves MP for ALCORT)
    p_pois = _make_party(
        level=10, exp=950, gold=500, food=200, marks=[1, 1, 1, 1],
        weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC,
    )
    p_pois.members[0].status = Status.POISONED
    p_pois.members[0].hp = 400
    p_pois.members[2].mp = 15
    p_pois.members[2].wisdom = 50
    ts_pois = TownScreen(party=p_pois, asset_mgr=am, map_id=10, start_x=33, start_y=60)
    sm.set_screen(ts_pois)
    ctrl._key_queue.clear()
    k_pois = ctrl.step(sm)
    assert k_pois != pygame.K_c  # did not cast SANCTU at 15 MP while poisoned

    # Exodus Castle (map_id=2) from entrance (32, 62) fights through ATTACK_AVATAR guards/floor traps and wins
    p_exo = _make_party(
        level=25, exp=2400, gold=100, food=500, marks=[1, 1, 1, 1], cards=[1, 1, 1, 1],
        weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC, map_id=2,
    )
    p_exo.members[0].strength = 50
    p_exo.members[1].strength = 50
    sm_exo = StateMachine(asset_mgr=am, audio=None)
    ts_exo = TownScreen(party=p_exo, asset_mgr=am, map_id=2, start_x=32, start_y=62)
    sm_exo.push_screen(ts_exo)
    ctrl_exo = AutoPlayController(enabled=True)
    from py_exodus import debug as _dbg
    prev_nohurt = _dbg.CHEATS.nohurt
    _dbg.CHEATS.nohurt = True
    try:
        for _ in range(1500):
            if getattr(p_exo, "exodus_defeated", 0) > 0:
                break
            ctrl_exo.step(sm_exo)
            sm_exo.update(0.05)
    finally:
        _dbg.CHEATS.nohurt = prev_nohurt
    assert p_exo.exodus_cards_status == 0xF
    assert getattr(p_exo, "exodus_defeated", 0) > 0

    # CONQUER_EXODUS at (10, 59) on ship yells EVOCARE to clear the Great Earth Serpent at (10, 57..58)
    p_evo = _make_party(
        level=25, exp=2400, gold=100, food=500, marks=[1, 1, 1, 1], cards=[1, 1, 1, 1],
        weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC, transport=Transport.SHIP,
    )
    p_evo.x, p_evo.y = 10, 59
    ow_evo = OverworldScreen(party=p_evo, map_id=0, asset_mgr=am, random_encounters=False)
    sm_evo = StateMachine(asset_mgr=am, audio=None)
    sm_evo.set_screen(ow_evo)
    ctrl_evo = AutoPlayController(enabled=True)
    for _ in range(12):
        ctrl_evo.step(sm_evo)
        if str(getattr(ow_evo.game_map.get_tile(10, 58), "name", "")).lower() == "water":
            break
    assert str(getattr(ow_evo.game_map.get_tile(10, 58), "name", "")).lower() == "water"
    assert str(getattr(ow_evo.game_map.get_tile(10, 57), "name", "")).lower() == "water"


def _make_stub_grid(width: int, height: int, tiles: dict[tuple[int, int], str], default: str = "water", map_id: int = 0):
    """Build a minimal wrap-around stub GameMap for isolated autoplay policy tests."""
    from types import SimpleNamespace

    def _tile_obj(name: str):
        swimmable = name in ("water", "whirlpool")
        walkable = name in ("grass", "sand", "brush", "forest", "floor", "cobblestone", "path")
        return SimpleNamespace(
            name=name,
            swimmable=swimmable,
            sailable=swimmable,
            walkable=walkable,
            passable=walkable,
            dispelable=False,
            attribs=0,
        )

    class _StubMap:
        def __init__(self):
            self.id = map_id
            self.width = width
            self.height = height
            self.border_behavior = "wrap"
            self.moongates = ()
            self.npcs = ()

        def get_tile(self, x: int, y: int):
            return _tile_obj(tiles.get((x % width, y % height), default))

    return _StubMap()


def _stub_screen(**kwargs):
    """Build a minimal stub OverworldScreen accepted by StateMachine.set_screen and AutoPlayController."""
    from types import SimpleNamespace

    class OverworldScreen:
        def __init__(self, **attrs):
            self.on_enter = lambda *a: None
            self.on_exit = lambda *a: None
            self.handle_event = lambda e: None
            self.is_finished = False
            self.text_log = SimpleNamespace(is_waiting_for_input=False, lines=[])
            self.creatures = []
            for k, v in attrs.items():
                setattr(self, k, v)

    return OverworldScreen(**kwargs)


def test_marooned_fallback_routes_to_hunt_patrol_never_space(pygame_setup):
    """Marooned FOOT party with no reachable portal, frigate, or moongate patrols via hunt fallback, never K_SPACE."""
    gmap = _make_stub_grid(6, 6, {(2, 2): "grass", (3, 2): "grass", (5, 5): "grass"})
    party = _make_party(level=5, exp=500, gold=100, food=500, transport=Transport.FOOT)
    party.x, party.y = 2, 2
    sm = StateMachine(asset_mgr=None, audio=None)
    screen = _stub_screen(game_map=gmap, creatures=[], party=party)
    sm.set_screen(screen)
    ctrl = AutoPlayController(enabled=True)
    key = ctrl._enter_portal_or_wait_dawn(sm, screen, gmap, party, 2, 2, (5, 5))
    assert key == pygame.K_RIGHT


def test_water_standoff_unconditional_full_hp(pygame_setup):
    """Full-HP party on water in pirate seas still steps away to >= 3 Manhattan from a pirate."""
    gmap = _make_stub_grid(7, 7, {}, default="water", map_id=0)
    party = _make_party(
        level=10, exp=1000, gold=100, food=500, marks=[1, 1, 1, 1],
        weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC, transport=Transport.SHIP,
    )
    party.x, party.y = 3, 3
    party.wind_direction = Direction.NORTH
    sm = StateMachine(asset_mgr=None, audio=None)
    screen = _stub_screen(
        game_map=gmap,
        creatures=[{"x": 3, "y": 5, "tile_name": "pirate"}],
        party=party,
        heading=Direction.NORTH,
        ship_hull=50,
    )
    sm.set_screen(screen)
    ctrl = AutoPlayController(enabled=True)
    assert ctrl.step(sm) == pygame.K_UP


def test_starving_override_keeps_avoid_within_limit(pygame_setup):
    """Starving BUY_FOOD party keeps _overworld_avoid when a detour within _STARVING_AVOID_MAX_STEPS exists."""
    gmap = _make_stub_grid(7, 7, {}, default="grass", map_id=0)
    party = _make_party(level=5, exp=500, gold=100, food=0, transport=Transport.FOOT)
    party.x, party.y = 3, 3
    sm = StateMachine(asset_mgr=None, audio=None)
    screen = _stub_screen(game_map=gmap, creatures=[], party=party)
    sm.set_screen(screen)
    ctrl = AutoPlayController(enabled=True)
    ctrl._overworld_avoid = {(3, 2)}
    assert ctrl._move_toward(sm, gmap, party, (3, 3), {(3, 1)}) != pygame.K_UP


def test_starving_override_relaxes_avoid_when_no_safe_route_within_limit(pygame_setup):
    """Starving BUY_FOOD party relaxes _overworld_avoid when avoid blocks all routes within _STARVING_AVOID_MAX_STEPS."""
    gmap = _make_stub_grid(7, 7, {}, default="grass", map_id=0)
    party = _make_party(level=5, exp=500, gold=100, food=0, transport=Transport.FOOT)
    party.x, party.y = 3, 3
    sm = StateMachine(asset_mgr=None, audio=None)
    screen = _stub_screen(game_map=gmap, creatures=[], party=party)
    sm.set_screen(screen)
    ctrl = AutoPlayController(enabled=True)
    ctrl._overworld_avoid = {(3, 2), (2, 3), (4, 3), (3, 4)}
    assert ctrl._move_toward(sm, gmap, party, (3, 3), {(3, 1)}) == pygame.K_UP


def test_kx_landing_refuses_pirate_adjacent_when_alternate_exists(pygame_setup):
    """K_x landing filter excludes pirate-adjacent shore tiles when a safe shore tile exists."""
    gmap = _make_stub_grid(7, 7, {(2, 1): "grass", (4, 1): "grass"}, default="water", map_id=0)
    party = _make_party(level=5, exp=500, gold=100, food=500, transport=Transport.SHIP)
    screen = _stub_screen(game_map=gmap, creatures=[{"x": 2, "y": 0, "tile_name": "pirate"}], party=party)
    safe = AutoPlayController._safe_shore_water(gmap, party, screen, {(2, 2), (4, 2)})
    assert (2, 2) not in safe


def test_broadsides_permitted_at_critical_hull(pygame_setup):
    """Ship with hull <= 30 still fires broadsides when a pirate is lined up."""
    gmap = _make_stub_grid(10, 10, {}, default="water", map_id=0)
    party = _make_party(
        level=10, exp=1000, gold=100, food=500, marks=[1, 1, 1, 1],
        weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC, transport=Transport.SHIP,
    )
    party.x, party.y = 4, 4
    party.ship_hull = 30
    sm = StateMachine(asset_mgr=None, audio=None)
    screen = _stub_screen(
        game_map=gmap,
        creatures=[{"x": 6, "y": 4, "tile_name": "pirate"}],
        party=party,
        heading=Direction.NORTH,
        ship_hull=30,
    )
    sm.set_screen(screen)
    ctrl = AutoPlayController(enabled=True)
    assert ctrl.step(sm) == pygame.K_f


def test_cure_poison_suppresses_sanctu_above_25_hp(pygame_setup):
    """CURE_POISON suppresses out-of-combat SANCTU heal detour unless a living member has <= 25 HP."""
    gmap = _make_stub_grid(7, 7, {}, default="grass", map_id=0)
    party = _make_party(level=5, exp=500, gold=200, food=500, transport=Transport.FOOT)
    party.x, party.y = 3, 3
    party.members[0].status = Status.POISONED
    party.members[0].hp = 40
    party.members[0].max_hp = 200
    party.members[2].mp = 20
    party.members[2].max_mp = 50
    sm = StateMachine(asset_mgr=None, audio=None)
    screen = _stub_screen(game_map=gmap, creatures=[], party=party)
    sm.set_screen(screen)
    ctrl = AutoPlayController(enabled=True)
    assert ctrl.step(sm) != pygame.K_c


def test_no_resting_on_unsafe_town_maps(pygame_setup):
    """Autoplay never rests with K_SPACE inside Exodus (2) or Death Gulch (10)."""
    from py_exodus.assets import AssetManager
    from py_exodus.screens.town import TownScreen

    am = AssetManager("data")
    am.load_all()
    party = _make_party(
        level=10, exp=1000, gold=100, food=500, marks=[1, 1, 1, 1],
        weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC,
    )
    party.members[0].hp = 150
    party.members[0].max_hp = 500
    party.members[2].mp = 0
    party.members[2].max_mp = 50
    ts = TownScreen(party=party, asset_mgr=am, map_id=10, start_x=13, start_y=8)
    sm = StateMachine(asset_mgr=am, audio=None)
    sm.set_screen(ts)
    ctrl = AutoPlayController(enabled=True)
    assert ctrl.step(sm) != pygame.K_SPACE


def test_cli_seed_flag():
    """CLI parse_args accepts --seed as an int (default None)."""
    from py_exodus.__main__ import parse_args

    assert parse_args(["--autoplay", "--seed", "437"]).seed == 437
    assert parse_args([]).seed is None














