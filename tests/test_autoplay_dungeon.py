"""Autoplay inside dungeons (autoplay round 1, user-approved 2026-11-25):
fountains, marks for every living member, deep-mark gates and turn-back
thresholds. The canonical party only (batch.build_party)."""
from __future__ import annotations

import random

import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.autoplay.batch import build_party
from py_exodus.autoplay.controller import AutoPlayController
from py_exodus.constants import ArmorType, Status, WeaponType
from py_exodus.state_machine import StateMachine
from py_exodus.world.loader import load_map
from py_exodus.world.map import DungeonTile

FIRE = 17  # Mark of Fire and Mark of Force, both on level 8 (z 7)


@pytest.fixture(scope="module")
def am():
    pygame.init()
    if not pygame.font.get_init():
        pygame.font.init()
    mgr = AssetManager("data")
    mgr.load_all()
    yield mgr


def _party(level: int = 8, marks=(1, 0, 0, 0)):
    """The canonical party (Thief, Fighter, Cleric, Wizard), exotics, fed,
    at full HP; ``marks`` for every member."""
    party = build_party()
    for m in party.members:
        m.level = level
        m.max_hp = m.hp = level * 100 + 50
        m.marks = list(marks)
        m.cards = [0, 0, 0, 0]
        m.weapons[WeaponType.EXOTIC] = 1
        m.weapon = WeaponType.EXOTIC
        m.armors[ArmorType.EXOTIC] = 1
        m.armor = ArmorType.EXOTIC
        m.food = 500
        m.torches = 5
    party.map_id = FIRE
    return party


def _dungeon(am, party, map_id: int, at: tuple[int, int, int]):
    from py_exodus.screens.dungeon_screen import DungeonScreen

    random.seed(7)
    dmap = load_map(map_id, am)
    sm = StateMachine(asset_mgr=am, audio=None)
    ds = DungeonScreen(party=party, dungeon_map=dmap, asset_mgr=am)
    ds.state.random_encounters_enabled = False
    ds.state.rng.seed(7)
    ds.state.x, ds.state.y, ds.state.z = at
    sm.set_screen(ds)
    return sm, ds


def _drinks(monkeypatch, ds) -> list[tuple[DungeonTile, int]]:
    """Record every drink: (fountain tile, 0-based member)."""
    calls: list[tuple[DungeonTile, int]] = []
    real = ds.state.drink_fountain

    def spy(member_index: int = 0):
        calls.append((ds.state.current_tile, member_index))
        return real(member_index)

    monkeypatch.setattr(ds.state, "drink_fountain", spy)
    return calls


# --- Item 1: fountains -------------------------------------------------------


def test_fountain_types_come_from_map_position(am):
    """Autoplay reads fountain types off the loaded map, which types them by
    x & 3 (0 poison, 1 heal, 2 acid, 3 cure; UltimaDngn.c:243)."""
    dmap = load_map(FIRE, am)
    heal = AutoPlayController._find_dungeon_tiles(dmap, {DungeonTile.FOUNTAIN_HEAL})
    assert (13, 5, 1) in heal and (9, 9, 4) in heal
    assert all(x & 3 == 1 for x, _y, _z in heal)
    cure = AutoPlayController._find_dungeon_tiles(dmap, {DungeonTile.FOUNTAIN_CURE})
    assert all(x & 3 == 3 for x, _y, _z in cure)


def test_heal_fountain_each_hurt_member_drinks_once_then_steps_off(am, monkeypatch):
    party = _party()
    party.members[1].hp = 100
    party.members[3].hp = 300
    sm, ds = _dungeon(am, party, FIRE, (13, 5, 1))  # heal fountain
    calls = _drinks(monkeypatch, ds)
    ctrl = AutoPlayController(enabled=True)
    left_at = None
    for i in range(40):
        ctrl.step(sm)
        if (ds.state.x, ds.state.y, ds.state.z) != (13, 5, 1):
            left_at = i
            break
    assert sorted(idx for _t, idx in calls) == [1, 3]
    assert all(m.hp == m.max_hp for m in party.members)
    assert left_at is not None
    assert not ds.text_log.is_waiting_for_input or "drink" not in (ds.text_log.current_prompt or "").lower()


def test_never_drinks_acid_or_poison(am, monkeypatch):
    for at in ((14, 5, 1), (8, 5, 0)):  # acid, poison
        party = _party()
        party.members[1].hp = 100
        sm, ds = _dungeon(am, party, FIRE, at)
        calls = _drinks(monkeypatch, ds)
        ctrl = AutoPlayController(enabled=True)
        ds.state.fixture_due = True
        ds._run_fixture()  # the question is up, on the bad fountain
        assert "drink" in ds.text_log.current_prompt.lower()
        ctrl.step(sm)
        assert not ds.text_log.is_waiting_for_input
        for _ in range(30):
            ctrl.step(sm)
        assert not [c for c in calls if c[0] in (DungeonTile.FOUNTAIN_ACID,
                                                  DungeonTile.FOUNTAIN_POISON)]


def test_cure_fountain_cures_the_poisoned_only(am, monkeypatch):
    party = _party()
    party.members[2].status = Status.POISONED
    sm, ds = _dungeon(am, party, FIRE, (15, 5, 1))  # cure fountain
    calls = _drinks(monkeypatch, ds)
    ctrl = AutoPlayController(enabled=True)
    for _ in range(10):
        ctrl.step(sm)
    assert [idx for _t, idx in calls] == [2]
    assert party.members[2].status == Status.GOOD


def test_hurt_party_heals_at_a_fountain_before_leaving(am):
    """Hurt on level 2 (z 1), on the way out: the heal fountain at
    (13, 5, 1) comes before the exit."""
    party = _party(marks=(1, 1, 0, 1))  # nothing wanted here: heading out
    for m in party.members:
        m.hp = m.max_hp // 2
    sm, ds = _dungeon(am, party, FIRE, (11, 5, 1))
    ctrl = AutoPlayController(enabled=True)
    for _ in range(80):
        ctrl.step(sm)
        if all(m.hp == m.max_hp for m in party.members):
            break
    assert all(m.hp == m.max_hp for m in party.members)
    assert sm.current_screen is ds


def test_poisoned_member_walks_to_a_cure_fountain(am):
    party = _party(marks=(1, 1, 0, 1))
    party.members[0].status = Status.POISONED
    sm, ds = _dungeon(am, party, FIRE, (11, 5, 1))
    ctrl = AutoPlayController(enabled=True)
    for _ in range(80):
        ctrl.step(sm)
        if party.members[0].status == Status.GOOD:
            break
    assert party.members[0].status == Status.GOOD
    assert sm.current_screen is ds


# --- Item 2: a mark is a goal until every living member has it ----------------


def _surface(party):
    party.map_id = 0
    party.gold = 0
    for m in party.members:
        m.cards = [1, 1, 1, 1]
        m.gold = 0
    return party


def test_remaining_marks_need_every_living_member():
    from py_exodus.autoplay.planner import Goal, evaluate_goal

    party = _surface(_party(marks=(1, 1, 1, 1)))
    party.members[2].marks[3] = 0  # the Cleric lacks Force
    assert evaluate_goal(party, 0) == Goal.GET_REMAINING_MARKS
    # A dead member's missing mark does not count.
    party.members[2].hp = 0
    party.members[2].status = Status.DEAD
    assert evaluate_goal(party, 17) != Goal.GET_REMAINING_MARKS


def test_unfixable_rod_does_not_send_the_party_in(am):
    """Loop guard: under 10 rations (and too broke for food) nobody can be
    made safe for the rod, so walking in would only walk out again."""
    from py_exodus.autoplay.planner import Goal, evaluate_goal

    party = _surface(_party(marks=(1, 0, 0, 0)))
    for m in party.members:
        m.hp = 100  # 100 - 50 < max/2 for everyone
        m.mp = 0
        m.food = 5
    assert evaluate_goal(party, 0) == Goal.GRIND_AND_LEVEL


def test_weak_member_heals_at_a_fountain_and_comes_back_for_the_mark(am):
    """Fires of Hell level 8: the Fighter lacks Force (4, 10, 7) and would
    drop under half health; the Cleric has no MP. The heal fountain at
    (9, 7, 7) comes first, then the rod."""
    party = _party(marks=(1, 1, 0, 1))
    fighter = party.members[1]
    fighter.marks[3] = 0
    fighter.hp = 300  # of 850: 250 after the burn, under 425
    for m in party.members:
        m.mp = 0
        m.marks[2] = 1  # nothing else wanted
    sm, ds = _dungeon(am, party, FIRE, (4, 10, 7))
    ctrl = AutoPlayController(enabled=True)
    healed = False
    for _ in range(200):
        ctrl.step(sm)
        healed = healed or fighter.hp == fighter.max_hp
        if fighter.marks[3]:
            break
    assert healed and fighter.marks[3] > 0
    assert fighter.hp == fighter.max_hp - 50
