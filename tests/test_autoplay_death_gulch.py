"""Death Gulch raids with moving townspeople (live trace 2026-11-22).

The pub's chests sit behind its counters and can never be reached; the raid
kept them as targets and, re-routing every turn around the pub's wandering
thieves, circled (53-54,32-33) for thousands of steps. And with the Cleric
out of MP the raid switched off, walked toward the exit, and walked back at
5 MP: a round trip per chest.
"""
import os
import random

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from py_exodus.autoplay import batch
from py_exodus.autoplay.controller import AutoPlayController
from py_exodus.autoplay.nav import reachable_2d
from py_exodus.constants import ArmorType, Profession, Transport, WeaponType
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.state_machine import StateMachine
from py_exodus.world import portal_entry


def _raid_party():
    p = batch.build_party()
    for m, lv, hp in zip(p.members, (23, 22, 13, 16), (2350, 2250, 1350, 1650)):
        m.level = lv
        m.max_hp = m.hp = hp
        m.food = 398
        m.keys = 9
        m.gold = 1870
        m.marks = [1, 1, 1, 1]
        m.cards = [1, 1, 1, 1]
        m.weapon = WeaponType.EXOTIC
        m.armor = ArmorType.EXOTIC
        m.dex = 40
    return p


def _in_death_gulch(p):
    am = batch._assets()
    sm = StateMachine(asset_mgr=am, audio=None)
    sm.set_screen(OverworldScreen(party=p, asset_mgr=am))
    p.x, p.y = 56, 31
    assert portal_entry.enter_portal(sm.current_screen, 56, 31)
    sm.update(batch.FRAME_DT)
    town = sm.current_screen
    # Mid-raid: the guards have been bribed away (the FIXED guard at
    # (33,56) closes the gold room's corridor until then).
    town.game_map.npcs = [n for n in town.game_map.npcs if n.tile_name != "guard"]
    return sm, town


def test_pub_chests_are_not_reachable_raid_targets():
    pygame.init()
    p = _raid_party()
    sm, town = _in_death_gulch(p)
    gm = town.game_map
    fixed = [n for n in gm.npcs if n.movement == "FIXED"]
    saved = gm.npcs
    gm.npcs = fixed
    try:
        reach = reachable_2d(gm, (53, 33), Transport.FOOT, party=p,
                             avoid_tiles={(n.x, n.y) for n in fixed}, allow_locked_doors=True)
    finally:
        gm.npcs = saved
    assert gm.get_tile(53, 29).name == "chest" and gm.get_tile(53, 36).name == "chest"
    assert (53, 29) not in reach and (53, 36) not in reach
    assert gm.get_tile(23, 56).name == "chest" and (23, 56) in reach  # the gold room


def test_raid_waits_for_mana_instead_of_walking_out_and_back():
    pygame.init()
    pygame.font.init()
    rng = random.getstate()
    try:
        random.seed(1)
        p = _raid_party()
        for m in p.members:
            m.gold = 1000  # still short of the trip, so still raiding
        cleric = next(m for m in p.members if m.profession == Profession.CLERIC)
        cleric.wisdom = 35
        cleric.mp = 0
        sm, town = _in_death_gulch(p)
        town.avatar_x, town.avatar_y = 24, 56  # in the gold room, chests around
        assert town.game_map.get_tile(23, 56).name == "chest"
        ctrl = AutoPlayController(enabled=True)
        sm.autoplay_enabled = True
        for _ in range(8):
            assert ctrl.step(sm) == pygame.K_SPACE
            sm.update(0.1)
        assert (town.avatar_x, town.avatar_y) == (24, 56)
    finally:
        random.setstate(rng)


def test_ship_parked_on_sosaria_does_not_open_the_pub_counter():
    """Live traces 2026-11-22: the frigate left on Sosaria at (54,31) made
    the counter's G at (54,31) in Death Gulch walkable; the party stepped
    onto the counter, the merchant attacked, and it looted behind it."""
    from py_exodus.constants import Direction
    from py_exodus.ui.renderer import can_move_to

    pygame.init()
    p = _raid_party()
    sm, town = _in_death_gulch(p)
    p.dynamic_objects = [{"tile": "frigate", "x": 54, "y": 31}]
    assert p.objects_map_id == 0
    assert not can_move_to(town.game_map, 54, 31, Transport.FOOT, party=p)
    town.avatar_x, town.avatar_y = 54, 32
    town._try_move(Direction.NORTH)
    assert (town.avatar_x, town.avatar_y) == (54, 32)


# --- B-15: a town fight turns the guards and Lord British into hunters -----
# (LairWare Combat, UltimaSpellCombat.c:873-876; user ruling 2026-11-25).
# Guards take no melee damage (B-11) and 8 come to a fight (B-09), so a
# hunting guard reaching the party is a wipe: autoplay keeps out of reach
# of hostile people and, once the guards hunt, bribes or walks out.


def _all_guards_hunt(town):
    for n in town.game_map.npcs:
        if n.tile_index in (18, 19):
            n.movement = "ATTACK_AVATAR"


def _in_death_gulch_with_guards(p):
    am = batch._assets()
    sm = StateMachine(asset_mgr=am, audio=None)
    sm.set_screen(OverworldScreen(party=p, asset_mgr=am))
    p.x, p.y = 56, 31
    assert portal_entry.enter_portal(sm.current_screen, 56, 31)
    sm.update(batch.FRAME_DT)
    return sm, sm.current_screen


def test_raid_keeps_out_of_the_gold_room_merchants_reach():
    """The gold room's merchant (16,54, ctrl 0xC0) walks row 54 after the
    party; a party on row 55 gets attacked (MoveMonsters, UltimaMisc.c:
    1197-1203) and the fight turns all 15 guards. Its row-55 chests are
    never raid targets and the party never stands next to its walk."""
    pygame.init()
    pygame.font.init()
    rng = random.getstate()
    try:
        random.seed(3)
        p = _raid_party()
        for m in p.members:
            m.gold = 1000
            m.mp = 50
        sm, town = _in_death_gulch(p)
        gm = town.game_map
        # Inside the merchant's room (the Mark of Force passes its field at
        # (20,56)), on a chest, with row 55's chests one step north.
        assert gm.get_tile(15, 55).name == "chest" and gm.get_tile(15, 56).name == "chest"
        town.avatar_x, town.avatar_y = 15, 56
        ctrl = AutoPlayController(enabled=True)
        sm.autoplay_enabled = True
        for _ in range(30):
            ctrl.step(sm)
            sm.update(0.1)
            assert sm.current_screen is town, "the merchant attacked"
            assert town.avatar_y != 55
            assert all(gm.get_tile(x, 55).name == "chest" for x in range(13, 20))
    finally:
        random.setstate(rng)


def test_hunting_guard_next_to_the_party_is_bribed():
    """LairWare Bribe (UltimaMisc.c:2446-2464) sends any guard away for 100
    gold, a hunting one too; a cardinal neighbour is bribed before its
    MoveMonsters step starts a fight the party cannot win."""
    pygame.init()
    pygame.font.init()
    p = _raid_party()
    sm, town = _in_death_gulch_with_guards(p)
    _all_guards_hunt(town)
    guard = next(n for n in town.game_map.npcs if n.tile_index == 18)
    town.avatar_x, town.avatar_y = 6, 30
    guard.x, guard.y = 5, 30  # between the party and the west gate
    town.game_map.npcs = [guard]
    ctrl = AutoPlayController(enabled=True)
    sm.autoplay_enabled = True
    for _ in range(10):
        if guard not in town.game_map.npcs:
            break
        ctrl.step(sm)
        sm.update(0.1)
        assert type(sm.current_screen).__name__ != "CombatScreen", "the guard attacked"
    assert guard not in town.game_map.npcs


def test_hunting_guards_send_the_raid_out_of_town():
    """After a town fight the guards hunt for the rest of the visit; the
    raid stops (no chest opening) and the party walks for the exit."""
    from py_exodus.autoplay.nav import find_2d_step_and_cost

    pygame.init()
    pygame.font.init()
    p = _raid_party()
    for m in p.members:
        m.gold = 1000
        m.mp = 50
    sm, town = _in_death_gulch_with_guards(p)
    gm = town.game_map
    _all_guards_hunt(town)
    gm.npcs = [n for n in gm.npcs if (n.x, n.y) == (40, 29)]  # one far hunter
    town.avatar_x, town.avatar_y = 23, 56
    assert gm.get_tile(23, 56).name == "chest"
    exits = {(0, y) for y in range(gm.height)}

    def cost():
        return find_2d_step_and_cost(gm, (town.avatar_x, town.avatar_y), exits,
                                     Transport.FOOT, party=p, allow_locked_doors=True)[1]

    start = cost()
    ctrl = AutoPlayController(enabled=True)
    sm.autoplay_enabled = True
    for _ in range(4):
        key = ctrl.step(sm)
        assert key not in (pygame.K_c, pygame.K_g), "opened a chest"
        sm.update(0.1)
    assert gm.get_tile(23, 56).name == "chest"
    assert cost() < start
