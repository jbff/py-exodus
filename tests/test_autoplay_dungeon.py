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
