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
# Eight guards come to that fight (B-09) and Lord British can't be hurt
# (B-11), so a hunting guard reaching the party is a hard fight at best:
# autoplay keeps out of reach of hostile people and, once the guards hunt,
# bribes or walks out.


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


def test_raid_keeps_out_of_the_armour_merchants_reach():
    """The armour shop's merchant (16,54, ctrl 0xC0) walks row 54 after the
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


def _cheb(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def _flee_setup(member_gold):
    pygame.init()
    pygame.font.init()
    p = _raid_party()
    for m in p.members:
        m.gold = member_gold
    sm, town = _in_death_gulch_with_guards(p)
    gm = town.game_map
    _all_guards_hunt(town)
    guards = [n for n in gm.npcs if n.tile_index == 18]
    town._move_people = lambda: None  # look at the party's step alone
    town.avatar_x, town.avatar_y = 30, 32
    return sm, town, guards


def test_flee_fallback_steps_out_of_reach_of_every_hunter():
    """Every exit route crosses a hunter's reach (15 hunting guards), so the
    flee falls back to a route around people. Its step must still end at
    least 2 from every hunter: a 0xC0 person attacks from any of the 8
    neighbours (MoveMonsters, UltimaMisc.c:1197-1203), diagonals too."""
    sm, town, guards = _flee_setup(member_gold=1000)
    gm = town.game_map
    spots = [(31, 31), (28, 32), (33, 33)]  # NE diagonal, 2 west, far SE
    for g, xy in zip(guards, spots):
        g.x, g.y = xy
    gm.npcs = guards[: len(spots)]
    ctrl = AutoPlayController(enabled=True)
    sm.autoplay_enabled = True
    ctrl.step(sm)
    pos = (town.avatar_x, town.avatar_y)
    assert pos != (30, 32)
    assert min(_cheb(pos, (n.x, n.y)) for n in gm.npcs) >= 2, pos


def test_no_join_gold_with_a_guard_at_hand():
    """Join Gold takes a turn, and a guard next to the party attacks on it.
    With nobody holding the 100 gold, step away instead."""
    sm, town, guards = _flee_setup(member_gold=60)
    gm = town.game_map
    guards[0].x, guards[0].y = 31, 32  # east, bribable but nobody has 100
    gm.npcs = guards[:1]
    ctrl = AutoPlayController(enabled=True)
    sm.autoplay_enabled = True
    key = ctrl.step(sm)
    assert key != pygame.K_j
    pos = (town.avatar_x, town.avatar_y)
    assert _cheb(pos, (31, 32)) >= 2, pos


def test_walking_out_past_hunters_never_paces_in_the_armour_shop():
    """User-approved 2026-11-25 (coordinator sim dg_escape.py): with Death
    Gulch's guards and the armour merchant hunting, a level-9 party in the
    armour shop paced (16,56)<->(16,57) for good: every step 2 or more from
    the hunters led nowhere (the one gap east, (26,56), held a guard), so
    _walk_out_of_town picked a "clear" tile with no way out, then the one
    it had come from. It now leaves such steps out, takes the route when it
    paces, and with people blocking every way out fights the nearest
    hunter. The party reaches the overworld."""
    pygame.init()
    random.seed(0)
    from py_exodus.world import tile_effects

    tile_effects._rng.seed(0)
    p = batch.build_party()
    for m in p.members:
        m.level = 9
        m.max_hp = m.hp = 950
        m.strength = m.dexterity = 50
        m.weapons[WeaponType.EXOTIC] = 1
        m.weapon = WeaponType.EXOTIC
        m.armors[ArmorType.EXOTIC] = 1
        m.armor = ArmorType.EXOTIC
        m.food, m.gold, m.keys, m.torches = 500, 500, 1, 5
        m.marks = [1, 1, 1, 1]
    am = batch._assets()
    sm = StateMachine(asset_mgr=am, audio=None)
    ow = OverworldScreen(party=p, asset_mgr=am)
    sm.set_screen(ow)
    p.x, p.y = 56, 31
    assert portal_entry.enter_portal(ow, 56, 31)
    town = sm.current_screen
    portal_entry.set_coords(town, 16, 55)
    p.x, p.y = 16, 55
    for n in town.game_map.npcs:
        if getattr(n, "tile_index", -1) in (18, 19):  # guards; the merchant hunts too
            n.movement = "ATTACK_AVATAR"
    for n in town.game_map.npcs:
        if (n.x, n.y) == (16, 54):
            n.movement = "ATTACK_AVATAR"
    ctrl = AutoPlayController(enabled=True, step_interval=0.0)
    sm.autoplay_enabled = True
    for _ in range(1500):
        ctrl.update(batch.FRAME_DT, sm)
        sm.update(batch.FRAME_DT)
        if isinstance(sm.current_screen, OverworldScreen):
            break
    assert isinstance(sm.current_screen, OverworldScreen)
    assert not p.is_party_dead()
