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


def test_desired_transport_is_pure_routing_for_grind(asset_map=None):
    """2026-11-21 doctrine: transport = f(where you are, where you're
    going). GRIND's destination is the Britain hub - foot there, SHIP only
    when water separates you from it."""
    from py_exodus.assets import AssetManager
    from py_exodus.world.loader import MapLoader

    am = AssetManager("data")
    am.load_all()
    gmap = MapLoader(am).load_map(0)
    ctrl = AutoPlayController(enabled=True)
    party = _grind_party(ctrl)
    # On the mainland near Britain: foot.
    party.x, party.y = 44, 20
    assert (
        ctrl._desired_transport(
            "GRIND_AND_LEVEL", party, gmap=gmap, px=party.x, py=party.y
        )
        == "FOOT"
    )
    # On the exotic isle: water separates -> SHIP.
    party.x, party.y = 24, 4
    assert (
        ctrl._desired_transport(
            "GRIND_AND_LEVEL", party, gmap=gmap, px=party.x, py=party.y
        )
        == "SHIP"
    )


def test_desired_transport_buy_food_wants_foot():
    ctrl = AutoPlayController(enabled=True)
    party = _grind_party(ctrl)
    assert ctrl._desired_transport("BUY_FOOD", party) == "FOOT"


def test_desired_transport_dig_exotics_is_pure_routing():
    """DIG's destination is the nearest dig ground: ship while water
    separates, FOOT once at/near the spot (2026-11-21: hardcoded SHIP made
    the reconciler re-board forever at the dig isle)."""
    from py_exodus.assets import AssetManager
    from py_exodus.world.loader import MapLoader

    am = AssetManager("data")
    am.load_all()
    gmap = MapLoader(am).load_map(0)
    ctrl = AutoPlayController(enabled=True)
    party = _grind_party(ctrl)
    # At the exotic isle (foot): dig grounds are here -> FOOT.
    party.x, party.y = 34, 3
    assert (
        ctrl._desired_transport("DIG_EXOTICS", party, gmap=gmap, px=34, py=3)
        == "FOOT"
    )
    # Far away on water: sail there.
    party.x, party.y = 50, 30
    assert (
        ctrl._desired_transport("DIG_EXOTICS", party, gmap=gmap, px=50, py=30)
        == "SHIP"
    )


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


def _walked_sm(x: int, y: int):
    party = type("_P", (), {"x": x, "y": y})()
    screen = type("_S", (), {"party": party})()
    return type("_SM", (), {"current_screen": screen})()


def test_lock_releases_when_pattern_stops_and_moved():
    ctrl = AutoPlayController(enabled=True)
    ctrl._engage_transport_lock("SHIP", reason="bx-cycle")
    ctrl._lock_anchor_pos = (4, 18)  # party walks away from the dock
    for i in range(AutoPlayController._LOCK_RELEASE_TICKS + 1):
        ctrl._record_step(_sig(pygame.K_RIGHT, x=5 + i, y=18))
        ctrl._tick_loop_breaker(_walked_sm(5 + i, 18))
    assert ctrl._transport_locked is None


def test_lock_sticks_while_party_has_not_moved():
    """Sticky-lock release (2026-11-20 live log): a quiet-ticks-only release
    recreated the dock B/X cycle at Britain under calm wind (X gated ->
    silent ticks -> release -> X -> re-lock forever). The lock must hold
    until the party actually moves off the anchor."""
    ctrl = AutoPlayController(enabled=True)
    ctrl._engage_transport_lock("SHIP", reason="bx-cycle")
    ctrl._lock_anchor_pos = (45, 16)
    for i in range(AutoPlayController._LOCK_MAX_TICKS // 2):
        ctrl._record_step(_sig(pygame.K_SPACE, x=45, y=16))
        ctrl._tick_loop_breaker(_walked_sm(45, 16))
    assert ctrl._transport_locked == "SHIP"
    # ... but the hard age cap always wins in the end.
    for i in range(AutoPlayController._LOCK_MAX_TICKS + 1):
        ctrl._tick_loop_breaker(_walked_sm(45, 16))
    assert ctrl._transport_locked is None


def test_desired_transport_all_town_goals_resolve():
    """Guard: every portal-shaped goal resolves its target table without
    unpack errors (the 2026-11-21 crash: 3-tuple tables unpacked as pairs)."""
    from py_exodus.assets import AssetManager
    from py_exodus.world.loader import MapLoader

    am = AssetManager("data")
    am.load_all()
    gmap = MapLoader(am).load_map(0)
    ctrl = AutoPlayController(enabled=True)
    party = _grind_party(ctrl)
    party.x, party.y = 44, 20
    for goal_name in (
        "CURE_POISON", "RESURRECT_DEAD", "BUY_FOOD", "OUTFIT_BRITAIN",
        "GET_REMAINING_MARKS", "GRIND_AND_LEVEL",
        "BUY_KEYS", "BUY_GEMS", "BUY_TORCHES",
    ):
        result = ctrl._desired_transport(goal_name, party, gmap=gmap, px=44, py=20)
        assert result in ("FOOT", "SHIP"), (goal_name, result)


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


# --- 2026-11-21 isle starvation (seed 63240257) ------------------------------


def _armor_only_party():
    """All members carry an EXOTIC weapon; none has exotic armor."""
    from py_exodus.constants import WeaponType

    party = _grind_party(exotics=False)
    for m in party.members:
        m.weapon = WeaponType.EXOTIC
        m.weapons[WeaponType.EXOTIC] = 1
    return party


def _weapon_only_party():
    """All members wear EXOTIC armor; none carries an exotic weapon."""
    from py_exodus.constants import ArmorType

    party = _grind_party(exotics=False)
    for m in party.members:
        m.armor = ArmorType.EXOTIC
        m.armors[ArmorType.EXOTIC] = 1
    return party


def test_dig_routing_follows_need_not_nearest_ground():
    """Root cause of the seed-63240257 isle B/X: routing picked the NEAREST
    dig ground while the DIG branch picks the ground for the gear still
    MISSING. At (34,3) with only armor left, DIG walks/boards to sail for
    (19,44) while routing said "FOOT to (33,3)" - so the reconciler kept
    yanking the party off the frigate and the DIG branch kept boarding.
    Routing must ask the same need-based question the branch asks."""
    from py_exodus.assets import AssetManager
    from py_exodus.world.loader import MapLoader

    am = AssetManager("data")
    am.load_all()
    gmap = MapLoader(am).load_map(0)
    ctrl = AutoPlayController(enabled=True)

    # Armor only -> the armor ground (19,44) lies across water -> SHIP.
    party = _armor_only_party()
    party.x, party.y = 34, 3
    assert (
        ctrl._desired_transport("DIG_EXOTICS", party, gmap=gmap, px=34, py=3)
        == "SHIP"
    ), "armor-only party at the weapon ground must route SHIP to the armor ground"

    # Weapon only -> the weapon ground (33,3) is one step away -> FOOT.
    party = _weapon_only_party()
    party.x, party.y = 34, 3
    assert (
        ctrl._desired_transport("DIG_EXOTICS", party, gmap=gmap, px=34, py=3)
        == "FOOT"
    ), "weapon-only party at the weapon ground must route FOOT"

    # Both needed -> nearest ground (mirrors the branch) -> FOOT here.
    party = _grind_party(exotics=False)
    party.x, party.y = 34, 3
    assert (
        ctrl._desired_transport("DIG_EXOTICS", party, gmap=gmap, px=34, py=3)
        == "FOOT"
    )


class _TraceSM:
    """Minimal StateMachine stand-in capturing emitted KEYDOWN events."""

    def __init__(self, screen):
        self.current_screen = screen
        self.keys: list[int] = []

    def handle_event(self, event):
        self.keys.append(event.key)


def _aboard_party(x, y):
    from py_exodus.constants import Transport

    party = _grind_party(exotics=False)
    party.x, party.y = x, y
    party.transport = Transport.SHIP
    party.ship_hull = 50
    party.dynamic_objects = [{"tile": "frigate", "x": x, "y": y}]
    return party


def _portal_screen(gmap, party):
    return type(
        "_Scr",
        (),
        {"game_map": gmap, "party": party, "trammel_phase": 1, "felucca_phase": 1},
    )()


def test_ship_prelude_never_disembarks_on_a_foreign_shore():
    """Root cause #2 of the seed-63240257 starvation: the ship prelude's
    "arrival" disembark fired at ANY walkable shore (with safety=True, so
    even a SHIP lock could not stop it). Aboard at (29,3) beside the exotic
    isle it X'd every tick; the reconciler re-boarded (water between it and
    the shop) -> B/X until the party starved. It must sail instead."""
    from py_exodus.assets import AssetManager
    from py_exodus.world.loader import MapLoader

    am = AssetManager("data")
    am.load_all()
    gmap = MapLoader(am).load_map(0)
    ctrl = AutoPlayController(enabled=True)
    party = _aboard_party(29, 3)
    screen = _portal_screen(gmap, party)
    sm = _TraceSM(screen)

    # (29,3) is water; (29,2)/(29,4) are walkable isle brush, so the old
    # "any shore" test disembarked here even though Britain (46,19) is
    # across open water.
    key = ctrl._enter_portal_or_wait_dawn(sm, screen, gmap, party, 29, 3, (46, 19))
    assert key != pygame.K_x, "must not disembark at a shore that does not reach the target"


def test_ship_prelude_still_disembarks_at_the_target_dock():
    """The arrival case must keep working: beside (46,19)'s dock water the
    party steps off (X) and walks in."""
    from py_exodus.assets import AssetManager
    from py_exodus.world.loader import MapLoader

    am = AssetManager("data")
    am.load_all()
    gmap = MapLoader(am).load_map(0)
    ctrl = AutoPlayController(enabled=True)
    party = _aboard_party(46, 18)  # dock water directly north of Britain
    screen = _portal_screen(gmap, party)
    sm = _TraceSM(screen)

    key = ctrl._enter_portal_or_wait_dawn(sm, screen, gmap, party, 46, 18, (46, 19))
    assert key == pygame.K_x, "arrival at the target dock must disembark"
