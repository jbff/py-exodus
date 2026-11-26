"""Fights where no monster can be reached (user-approved brief 2026-11-25).

The user's trace_20261125-184644: a ship fight from step 76,564, five
Man-O-Wars (squids) at Sosaria (31, 5), lasted about 3,200 autoplay steps.
A squid sat in the water beside the hull at (7, 8), the deck edge (7, 7) a
wall; the Exotic-armed melee members could not reach it and passed, and the
Wizard never lined up its Mittar. LW Shoot (UltimaSpellCombat.c:708-731)
has no terrain test: missiles and Mittar fly over walls and the rail.
"""
from __future__ import annotations

import random

import pytest

from py_exodus.autoplay.batch import _assets
from py_exodus.combat.arena import ActionType
from py_exodus.combat.auto_combat import choose_auto_combat_action
from py_exodus.constants import Spell, Transport
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.state_machine import StateMachine
from tests.test_autoplay_trip import _all_cards_party

THIEF, FIGHTER, CLERIC, WIZARD = range(4)


@pytest.fixture(scope="module")
def am():
    return _assets()


def _squid_fight(am, seed: int):
    """The trace's state at combat_start: the canonical party, level 25,
    Exotics, at sea at Sosaria (31, 5), HP and MP as the trace had them."""
    random.seed(seed)
    party = _all_cards_party(keys=8, gold=5000)
    for m, hp, mp in zip(party.members, (2138, 1997, 1818, 2078), (0, 0, 8, 25)):
        m.max_hp, m.hp, m.mp, m.food = 2550, hp, mp, 211
    party.x, party.y = 31, 5
    party.transport = Transport.SHIP
    sm = StateMachine(asset_mgr=am, audio=None)
    ow = OverworldScreen(
        party=party, map_id=0, asset_mgr=am, start_x=31, start_y=5, random_encounters=False
    )
    sm.set_screen(ow)
    ow.creatures = []
    ow._trigger_combat("squid", {"tile_name": "squid", "tile": "squid", "x": 31, "y": 4})
    cs = sm.current_screen
    assert type(cs).__name__ == "CombatScreen" and cs.arena.ship_battle
    return sm, cs, party


def _one_squid_by_the_hull(arena, members_at: dict[int, tuple[int, int]]):
    """One Man-O-War left, in the water at (7, 8) under the deck edge (7, 7)."""
    squid = arena.monsters[0]
    arena.monsters = [squid]
    squid.x, squid.y = 7, 8
    assert arena.combat_map.get_tile(7, 7).name == "wall"
    for i in list(arena.player_positions):
        if i not in members_at:
            arena.player_positions.pop(i)
    arena.player_positions.update(members_at)
    return squid


def test_the_wizard_walks_to_line_up_mittar_on_a_squid_by_the_hull(pygame_setup, am):
    """Item A: from (3, 5) the old moves paced (3, 6) <-> (3, 7) at the
    rail for ever; now the Wizard walks to a deck square on the squid's
    column and casts."""
    sm, cs, party = _squid_fight(am, 3)
    arena = cs.arena
    _one_squid_by_the_hull(arena, {WIZARD: (3, 5)})
    party.members[WIZARD].mp = 25
    for _ in range(10):
        action = choose_auto_combat_action(arena, WIZARD)
        if action.type == ActionType.CAST:
            break
        assert action.type == ActionType.MOVE
        x, y = arena.player_positions[WIZARD]
        arena.player_positions[WIZARD] = (x + action.direction.dx, y + action.direction.dy)
    assert action.type == ActionType.CAST
    assert action.spell in (Spell.MITTAR, Spell.FULGAR)
    assert arena.player_positions[WIZARD][0] == 7


def test_the_line_up_square_avoids_a_monster_where_it_can(pygame_setup, am):
    """Item A: of the squares that line up a shot, one no monster stands
    next to wins over a nearer one beside a monster."""
    from py_exodus.combat.auto_combat import _line_up_step

    sm, cs, party = _squid_fight(am, 3)
    arena = cs.arena
    squid = _one_squid_by_the_hull(arena, {WIZARD: (6, 6)})
    # A second squid in the water east of the hull, at (9, 7). South, (6, 7)
    # lines it up but is next to the squid at (7, 8); east, (7, 6) lines up
    # the squid at (7, 8) and no monster stands next to it.
    arena.monsters.append(squid.__class__(squid.definition, 9, 7))
    d = _line_up_step(arena, WIZARD, 6, 6, arena.monsters)
    assert (6 + d.dx, 6 + d.dy) == (7, 6)


def test_no_line_up_square_keeps_the_old_moves(pygame_setup, am):
    """Item A: with no square that lines up a shot, no new move (never pace)."""
    from py_exodus.combat.auto_combat import _line_up_step

    sm, cs, party = _squid_fight(am, 3)
    arena = cs.arena
    squid = _one_squid_by_the_hull(arena, {WIZARD: (3, 5)})
    squid.x, squid.y = 0, 1  # open water, no deck square on its row or column
    assert _line_up_step(arena, WIZARD, 3, 5, arena.monsters) is None


# ---------------------------------------------------------------------------
# Item B: the Fighter and the Thief carry a plain Bow for unreachable fights
# ---------------------------------------------------------------------------


def _with_spare_bows(party):
    """The Thief and the Fighter, Exotic readied, each with one plain Bow
    in the pack (what autoplay now buys them)."""
    from py_exodus.constants import WeaponType

    for i in (THIEF, FIGHTER):
        party.members[i].weapons[WeaponType.BOW] = 1
    return party


def _play_fight(sm, cs, max_steps: int = 4000):
    """Drive the fight with the autoplay controller as a live run does;
    returns the kills as ``(member, action type, weapon)``."""
    from py_exodus.autoplay.batch import FRAME_DT
    from py_exodus.autoplay.controller import AutoPlayController

    ctrl = AutoPlayController(enabled=True, step_interval=0.01)
    sm.autoplay_enabled = True
    kills: list[tuple[int, str, str]] = []
    orig = cs._execute_action

    def _execute(action):
        idx = cs.arena.active_party_member_idx
        weapon = cs.arena.party.members[idx].weapon.name
        before = sum(1 for m in cs.arena.monsters if not m.is_dead)
        orig(action)
        after = sum(1 for m in cs.arena.monsters if not m.is_dead)
        kills.extend([(idx, action.type.value, weapon)] * (before - after))

    cs._execute_action = _execute
    for _ in range(max_steps):
        ctrl.step(sm)
        sm.update(FRAME_DT)
        if sm.current_screen is not cs:
            break
    return ctrl, kills


@pytest.mark.parametrize("seed", [1, 3, 5, 7])
def test_the_squid_fight_ends_in_bounded_rounds_with_bows_and_mittar(pygame_setup, am, seed):
    """The trace's fight on the repro's long seeds (145, 86, 226 and over
    1,800 rounds before; seed 7 lost the Fighter and the Wizard): with the
    spare Bows it ends within 40 rounds, nobody dies, and bow shots or the
    Wizard's spells make the kills."""
    sm, cs, party = _squid_fight(am, seed)
    _with_spare_bows(party)
    ctrl, kills = _play_fight(sm, cs)
    assert sm.current_screen is not cs, "the fight never ended"
    assert cs.arena.round_count <= 40
    assert not any(m.is_dead() for m in party.members)
    ranged = [k for k in kills if k[2] == "BOW" or k[1] == "cast"]
    assert ranged and len(ranged) >= len(kills) / 2


def test_the_next_fight_starts_with_the_exotic(pygame_setup, am):
    """Never end up in a fight still holding the Bow: back on the surface
    the members ready their Exotics before anything else."""
    from py_exodus.constants import WeaponType

    sm, cs, party = _squid_fight(am, 1)
    _with_spare_bows(party)
    ctrl, kills = _play_fight(sm, cs)
    assert sm.current_screen is not cs
    assert any(m.weapon == WeaponType.BOW for m in party.members)  # a bow won it
    for _ in range(12):
        if all(m.weapon == WeaponType.EXOTIC for m in party.members):
            break
        ctrl.step(sm)
        sm.update(1.0 / 60.0)
        assert type(sm.current_screen).__name__ != "CombatScreen"
    assert [m.weapon for m in party.members] == [WeaponType.EXOTIC] * 4
    assert all(party.members[i].weapons.get(WeaponType.BOW, 0) == 1 for i in (THIEF, FIGHTER))


def test_the_bow_is_readied_only_when_nothing_can_be_reached(pygame_setup, am):
    """With a squid beside the hull, unreachable, the Fighter readies its
    Bow (one turn), then shoots or lines up; a monster on the deck, far but
    walkable to, keeps the Exotic; a squid next to the Bow holder (a cardinal
    side) has it ready the Exotic again."""
    from py_exodus.constants import WeaponType

    sm, cs, party = _squid_fight(am, 3)
    _with_spare_bows(party)
    arena = cs.arena
    fighter = party.members[FIGHTER]
    squid = _one_squid_by_the_hull(arena, {FIGHTER: (3, 5)})

    action = choose_auto_combat_action(arena, FIGHTER)
    assert action.type == ActionType.READY and action.weapon == WeaponType.BOW
    arena.active_party_member_idx = FIGHTER
    arena.execute_player_action(FIGHTER, action)
    assert fighter.weapon == WeaponType.BOW
    assert fighter.weapons[WeaponType.EXOTIC] == 1 and fighter.weapons[WeaponType.BOW] == 0
    # Holding the Bow, no more switching: it lines up (column 7) and shoots.
    for _ in range(6):
        action = choose_auto_combat_action(arena, FIGHTER)
        assert action.type in (ActionType.MOVE, ActionType.ATTACK)
        if action.type == ActionType.ATTACK:
            break
        x, y = arena.player_positions[FIGHTER]
        arena.player_positions[FIGHTER] = (x + action.direction.dx, y + action.direction.dy)
    assert action.type == ActionType.ATTACK and arena.player_positions[FIGHTER][0] == 7

    # A squid comes up beside the hull next to the Fighter: Exotic again.
    arena.player_positions[FIGHTER] = (3, 7)
    squid.x, squid.y = 3, 8
    action = choose_auto_combat_action(arena, FIGHTER)
    assert action.type == ActionType.READY and action.weapon == WeaponType.EXOTIC
    arena.active_party_member_idx = FIGHTER
    arena.execute_player_action(FIGHTER, action)
    assert fighter.weapon == WeaponType.EXOTIC
    # Next to it with the Exotic: it strikes, it doesn't switch back.
    assert choose_auto_combat_action(arena, FIGHTER).type == ActionType.ATTACK

    # A monster far off on the deck that a walk reaches: no Bow.
    squid.x, squid.y = 2, 4  # (as if a land monster) on the deck's far end
    arena.player_positions[FIGHTER] = (7, 6)
    action = choose_auto_combat_action(arena, FIGHTER)
    assert action.type == ActionType.MOVE


def test_the_bow_is_never_readied_in_castle_exodus(pygame_setup, am):
    """Only Exotics hit in Castle Exodus (B-21): no Bow there, even with
    nothing in reach, and a Bow held is put away."""
    from py_exodus.combat.arena import EXODUS_MAP_ID
    from py_exodus.constants import WeaponType

    sm, cs, party = _squid_fight(am, 3)
    _with_spare_bows(party)
    arena = cs.arena
    arena.context_map_id = EXODUS_MAP_ID
    _one_squid_by_the_hull(arena, {FIGHTER: (3, 5)})
    assert choose_auto_combat_action(arena, FIGHTER).type != ActionType.READY
    party.members[FIGHTER].ready_weapon(WeaponType.BOW, am)
    action = choose_auto_combat_action(arena, FIGHTER)
    assert action.type == ActionType.READY and action.weapon == WeaponType.EXOTIC


def _in_britain(am, party, steps: int):
    from py_exodus.autoplay.controller import AutoPlayController
    from py_exodus.screens.town import TownScreen

    random.seed(1)
    sm = StateMachine(asset_mgr=am, audio=None)
    ts = TownScreen(party=party, asset_mgr=am, map_id=3)
    sm.set_screen(ts)
    ctrl = AutoPlayController(enabled=True)
    for _ in range(steps):
        ctrl.step(sm)
        sm.update(1.0 / 60.0)
    return ts


def test_the_fighter_and_thief_each_buy_one_spare_bow(pygame_setup, am):
    """With the Exotic as their weapon, the Thief and the Fighter each buy
    one plain Bow (Britain's weapon shop, "f", 350) on a visit to a town
    with a weapon shop and keep the Exotic readied; nobody buys a second,
    and the Cleric and Wizard (no bows for their classes) buy none. The
    planner never makes a trip of it."""
    from py_exodus.autoplay.equipment import best_shop_upgrade
    from py_exodus.constants import WeaponType

    party = _all_cards_party(gold=2000)
    assert best_shop_upgrade(party) is None
    _in_britain(am, party, 500)
    assert [m.weapons.get(WeaponType.BOW, 0) for m in party.members] == [1, 1, 0, 0]
    assert [m.weapon for m in party.members] == [WeaponType.EXOTIC] * 4
    assert party.gold == 2000 - 2 * 350


def test_the_spare_bow_never_takes_a_trip_gold_back_under(pygame_setup, am):
    """A party holding its return trip's gold doesn't spend it on a Bow
    (it would raid again); the 500 gold reserve stays too."""
    from py_exodus.autoplay.planner import optional_purchase_ok, return_trip_gold
    from py_exodus.constants import WeaponType

    party = _all_cards_party(gold=2000)
    target = return_trip_gold(party)
    assert target > 0
    party.members[0].gold = target + 100
    assert not optional_purchase_ok(party, 350)
    _in_britain(am, party, 300)
    assert all(m.weapons.get(WeaponType.BOW, 0) == 0 for m in party.members)
    party.members[0].gold = target + 350
    assert optional_purchase_ok(party, 350)
    party.members[0].gold = 800
    assert not optional_purchase_ok(party, 350)


def test_the_spare_bow_is_never_sold(pygame_setup, am):
    """Selling spare gear on the way out of a shop town sells a spare
    Dagger but keeps each member's one spare Bow (before: the Bow, below
    the Exotic, was spare gear)."""
    from py_exodus.autoplay.equipment import excess_gear
    from py_exodus.constants import ArmorType, WeaponType

    party = _all_cards_party(gold=2000)
    _with_spare_bows(party)
    party.members[THIEF].weapons[WeaponType.DAGGER] = 2
    stock = frozenset(WeaponType) - {WeaponType.NONE}
    assert all(s.item != WeaponType.BOW for s in excess_gear(party, stock, frozenset(ArmorType), prefer_ranged=False))
    assert all(s.item != WeaponType.BOW for s in excess_gear(party, stock, frozenset(ArmorType), prefer_ranged=True))
    _in_britain(am, party, 500)
    assert party.members[THIEF].weapons.get(WeaponType.DAGGER, 0) == 0  # the sale ran
    assert [m.weapons.get(WeaponType.BOW, 0) for m in party.members] == [1, 1, 0, 0]
