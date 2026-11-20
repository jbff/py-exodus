"""Tests for the autoplay loop-breaker (memory layer over the goal ladder).

Root cause (2026-11-20 B/X starvation): the controller is an if-ladder with
no memory — the FOOT board branch and the SHIP disembark branch both fire on
the same party state near Britain, producing an endless B/X cycle that burns
a food unit per pass. This layer detects repeating cycle signatures in the
emitted-key history, derives the goal-correct transport, and locks out the
contrary transport action until real movement breaks the cycle.
"""
from __future__ import annotations

import pygame
import pytest

from py_exodus.autoplay.controller import AutoPlayController


def _sig(key, x=10, y=20, map_id=0, screen="OverworldScreen"):
    return (screen, map_id, (x, y), key)


# --- cycle detection --------------------------------------------------------


def test_detects_period2_bx_oscillation():
    hist = [_sig(k, x=4, y=18) for k in (pygame.K_b, pygame.K_x) * 4]
    ctrl = AutoPlayController(enabled=True)
    for s in hist:
        ctrl._record_step(s)
    assert ctrl._detect_transport_oscillation() is True


def test_detects_period2_after_partial_pattern():
    hist = [_sig(k, x=4, y=18) for k in (pygame.K_b, pygame.K_x) * 3]
    ctrl = AutoPlayController(enabled=True)
    for s in hist:
        ctrl._record_step(s)
    assert ctrl._detect_transport_oscillation() is True


def test_no_false_positive_on_normal_movement():
    # Walking east with occasional boards: keys alternate with MOVING positions.
    hist = []
    for i in range(8):
        hist.append(_sig(pygame.K_RIGHT, x=4 + i, y=18))
        hist.append(_sig(pygame.K_RIGHT, x=5 + i, y=18))
    ctrl = AutoPlayController(enabled=True)
    for s in hist:
        ctrl._record_step(s)
    assert ctrl._detect_transport_oscillation() is False


def test_no_false_positive_on_repeated_attack_in_same_spot():
    # Standing still attacking (period-1) is grind behavior, not B/X.
    hist = [_sig(pygame.K_a, 4, 18) for _ in range(8)]
    ctrl = AutoPlayController(enabled=True)
    for s in hist:
        ctrl._record_step(s)
    assert ctrl._detect_transport_oscillation() is False


def test_detector_needs_minimum_history():
    hist = [_sig(pygame.K_b, 4, 18), _sig(pygame.K_x, 4, 18)]
    ctrl = AutoPlayController(enabled=True)
    for s in hist:
        ctrl._record_step(s)
    assert ctrl._detect_transport_oscillation() is False


# --- transport gate ----------------------------------------------------------


def _grind_party(controller=None, marks=(1, 0, 0, 0), exotics=False, level=5):
    from py_exodus.constants import ArmorType, Profession, Race, WeaponType
    from py_exodus.entities.character import Character
    from py_exodus.entities.party import Party

    specs = ("THIEF", "FIGHTER", "CLERIC", "WIZARD")
    party = Party()
    for i, prof in enumerate(specs):
        c = Character(f"M{i}", "M", Race.HUMAN, getattr(Profession, prof), gold=400, food=400)
        c.level = level
        c.marks = list(marks)
        if exotics:
            c.weapon = WeaponType.EXOTIC
            c.weapons[WeaponType.EXOTIC] = 1
            c.armor = ArmorType.EXOTIC
            c.armors[ArmorType.EXOTIC] = 1
        party.add_member(c)
    return party


def test_desired_transport_grind_pre_sea_wants_ship():
    ctrl = AutoPlayController(enabled=True)
    party = _grind_party(ctrl)  # lvl 5, Mark of Kings, no exotics
    assert ctrl._desired_transport("GRIND_AND_LEVEL", party) == "SHIP"


def test_desired_transport_buy_food_wants_foot():
    ctrl = AutoPlayController(enabled=True)
    party = _grind_party(ctrl)
    assert ctrl._desired_transport("BUY_FOOD", party) == "FOOT"


def test_desired_transport_dig_exotics_wants_ship():
    ctrl = AutoPlayController(enabled=True)
    party = _grind_party(ctrl)
    assert ctrl._desired_transport("DIG_EXOTICS", party) == "SHIP"


def test_gate_blocks_disembark_when_ship_is_desired():
    ctrl = AutoPlayController(enabled=True)
    ctrl._engage_transport_lock("SHIP", reason="bx-cycle")
    assert ctrl._transport_action_allowed(pygame.K_x, desired="SHIP") is False
    # Boarding is the desired action: allowed.
    assert ctrl._transport_action_allowed(pygame.K_b, desired="SHIP") is True


def test_gate_blocks_board_when_foot_is_desired():
    ctrl = AutoPlayController(enabled=True)
    ctrl._engage_transport_lock("FOOT", reason="bx-cycle")
    assert ctrl._transport_action_allowed(pygame.K_b, desired="FOOT") is False
    assert ctrl._transport_action_allowed(pygame.K_x, desired="FOOT") is True


def test_lock_releases_when_pattern_stops():
    ctrl = AutoPlayController(enabled=True)
    ctrl._engage_transport_lock("SHIP", reason="bx-cycle")
    # Simulate the pattern breaking: new signatures at new positions.
    for i in range(AutoPlayController._LOCK_RELEASE_TICKS + 1):
        ctrl._record_step(_sig(pygame.K_RIGHT, x=4 + i, y=18))
        ctrl._tick_loop_breaker(object())
    assert ctrl._transport_locked is None


def test_lock_never_blocks_safety_disembark():
    """Hull-critical shore disembark (K_x) is a safety action — always allowed."""
    ctrl = AutoPlayController(enabled=True)
    ctrl._engage_transport_lock("SHIP", reason="bx-cycle")
    assert ctrl._transport_action_allowed(pygame.K_x, desired="SHIP", safety=True) is True


def test_cure_poison_overworld_travels_to_healer(pygame_setup):
    """Regression (2026-11-20 live stall): CURE_POISON on map 0 previously
    had NO overworld handler — a poisoned party with no ALCORT clerk idled
    at the Death Gulch portal forever. It must now travel toward a healer
    town instead of issuing nothing."""
    import pygame as pg

    from py_exodus.assets import AssetManager
    from py_exodus.constants import Status
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.state_machine import StateMachine

    from tests.test_autoplay import _make_party

    am = AssetManager("data")
    am.load_all()
    party = _make_party(level=20, gold=1000, map_id=0, x=55, y=30)
    for m in party.members:
        m.status = Status.POISONED
        m.mp = m.max_mp = 0  # no on-the-spot ALCORT possible
    sm = StateMachine(asset_mgr=am, audio=None)
    sm.push_screen(OverworldScreen(party=party, asset_mgr=am, random_encounters_enabled=False))

    ctrl = AutoPlayController(enabled=True)
    key = ctrl.step(sm)
    assert key is not None, "controller must act on an unhandled overworld cure goal"
