"""Autoplay sells spare weapons and armour in shop towns (user 2026-11-23)."""
from __future__ import annotations

from py_exodus.autoplay import batch
from py_exodus.autoplay.equipment import SpareGear, excess_gear
from py_exodus.constants import ArmorType, Profession, Status, WeaponType

ORDINARY_W = frozenset({WeaponType.DAGGER, WeaponType.MACE, WeaponType.SLING, WeaponType.AXE,
                        WeaponType.BOW, WeaponType.SWORD, WeaponType.SWORD_2H})
ORDINARY_A = frozenset({ArmorType.CLOTH, ArmorType.LEATHER, ArmorType.CHAIN, ArmorType.PLATE})


def _party():
    """build_party: Thief, Fighter, Cleric, Wizard, nothing spare."""
    p = batch.build_party()
    for m in p.members:
        for wt in list(m.weapons):
            m.weapons[wt] = 0
        for at in list(m.armors):
            m.armors[at] = 0
    return p


def _by_prof(p, prof):
    return next((i + 1, m) for i, m in enumerate(p.members) if m.profession == prof)


def test_a_fresh_party_has_nothing_to_sell():
    assert excess_gear(_party(), ORDINARY_W, ORDINARY_A) == []


def test_exotic_fighter_sells_old_sword_and_bow_once_melee_for_good():
    p = _party()
    idx, f = _by_prof(p, Profession.FIGHTER)
    f.weapon, f.armor = WeaponType.EXOTIC, ArmorType.EXOTIC
    f.weapons[WeaponType.SWORD] = 1
    f.weapons[WeaponType.BOW] = 1
    f.armors[ArmorType.PLATE] = 1
    for m in p.members:  # everyone past swords/bows
        if m is not f:
            m.weapon, m.armor = WeaponType.EXOTIC, ArmorType.EXOTIC
    sales = excess_gear(p, ORDINARY_W, ORDINARY_A, prefer_ranged=False)
    # The one plain Bow is the Exotic holder's spare (user ruling 2026-11-25,
    # unreachable fights): kept in either mode.
    assert set(sales) == {
        SpareGear(idx, "weapon", WeaponType.SWORD, 1),
        SpareGear(idx, "armor", ArmorType.PLATE, 1),
    }
    sales = excess_gear(p, ORDINARY_W, ORDINARY_A, prefer_ranged=True)
    assert SpareGear(idx, "weapon", WeaponType.BOW, 1) not in sales
    # A second Bow is spare gear once every Bow user holds one.
    f.weapons[WeaponType.BOW] = 2
    _by_prof(p, Profession.THIEF)[1].weapons[WeaponType.BOW] = 1
    sales = excess_gear(p, ORDINARY_W, ORDINARY_A, prefer_ranged=False)
    assert SpareGear(idx, "weapon", WeaponType.BOW, 1) in sales


def test_a_piece_another_member_would_use_is_kept():
    """The hand-off: the Thief, on a Dagger, would take the Fighter's spare
    Sword."""
    p = _party()
    _, f = _by_prof(p, Profession.FIGHTER)
    _, t = _by_prof(p, Profession.THIEF)
    f.weapon = WeaponType.SWORD_2H
    f.weapons[WeaponType.SWORD] = 2
    t.weapon = WeaponType.DAGGER
    sales = excess_gear(p, ORDINARY_W, ORDINARY_A)
    swords = [s for s in sales if s.item == WeaponType.SWORD]
    assert sum(s.count for s in swords) == 1  # one for the Thief, one sold


def test_magic_gear_sells_only_where_stocked():
    p = _party()
    idx, f = _by_prof(p, Profession.FIGHTER)
    f.weapon = WeaponType.EXOTIC
    f.weapons[WeaponType.AXE_P2] = 1
    for m in p.members:
        if m is not f:
            m.weapon = WeaponType.EXOTIC
    assert excess_gear(p, ORDINARY_W, ORDINARY_A, prefer_ranged=False) == []
    dawn = ORDINARY_W | {WeaponType.AXE_P2}
    assert excess_gear(p, dawn, ORDINARY_A, prefer_ranged=False) == [
        SpareGear(idx, "weapon", WeaponType.AXE_P2, 1)
    ]


def test_a_dead_members_gear_waits_for_the_resurrection():
    p = _party()
    _, f = _by_prof(p, Profession.FIGHTER)
    f.status = Status.DEAD
    f.weapons[WeaponType.SWORD] = 3
    f.armors[ArmorType.PLATE] = 1
    for m in p.members:
        if m is not f:
            m.weapon, m.armor = WeaponType.EXOTIC, ArmorType.EXOTIC
    assert excess_gear(p, ORDINARY_W, ORDINARY_A, prefer_ranged=False) == []


def test_wizard_keeps_a_dagger_over_bare_hands():
    p = _party()
    _, w = _by_prof(p, Profession.WIZARD)
    w.weapon = WeaponType.NONE
    w.weapons[WeaponType.DAGGER] = 1
    for m in p.members:
        if m is not w:
            m.weapon = WeaponType.EXOTIC
    assert excess_gear(p, ORDINARY_W, ORDINARY_A, prefer_ranged=False) == []


# --- the controller, in a real town --------------------------------------

import pygame  # noqa: E402
import pytest  # noqa: E402

from py_exodus.autoplay import controller as controller_mod  # noqa: E402
from py_exodus.autoplay.controller import AutoPlayController  # noqa: E402
from py_exodus.autoplay.planner import Goal  # noqa: E402


@pytest.fixture(scope="module")
def assets():
    import os

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    pygame.font.init()
    return batch._assets()


def _endgame_party():
    p = _party()
    for m in p.members:
        m.weapon, m.armor = WeaponType.EXOTIC, ArmorType.EXOTIC
        m.cards, m.marks = [1, 1, 1, 1], [1, 1, 1, 1]
        m.food, m.gold, m.hp = 300, 0, m.max_hp
    return p


def _in_grey(assets, monkeypatch, party, at=(29, 43), goal=Goal.GRIND_AND_LEVEL):
    from py_exodus.screens.town import TownScreen
    from py_exodus.state_machine import StateMachine

    monkeypatch.setattr(controller_mod, "evaluate_goal", lambda *a, **k: goal)
    sm = StateMachine(asset_mgr=assets, audio=None)
    ts = TownScreen(party=party, asset_mgr=assets, map_id=6, start_x=at[0], start_y=at[1])
    for n in ts.game_map.npcs:  # keepers stay home; nobody wanders into the way
        n.movement = "FIXED"
    sm.set_screen(ts)
    return sm, ts


def _run(sm, ts, ctrl, until, steps=400):
    for _ in range(steps):
        ctrl.step(sm)
        sm.update(0.05)
        if until() or sm.current_screen is not ts:
            break


def test_leaving_grey_sells_a_second_bow_and_keeps_the_spare(assets, monkeypatch):
    """The Exotic holder keeps one plain Bow for unreachable fights (user
    ruling 2026-11-25); a second one is sold (the Thief has its own)."""
    party = _endgame_party()
    idx, f = _by_prof(party, Profession.FIGHTER)
    f.weapons[WeaponType.BOW] = 2
    _by_prof(party, Profession.THIEF)[1].weapons[WeaponType.BOW] = 1
    f.armors[ArmorType.PLATE] = 1
    sm, ts = _in_grey(assets, monkeypatch, party)
    ctrl = AutoPlayController(enabled=True)
    _run(sm, ts, ctrl, lambda: f.weapons[WeaponType.BOW] == 1 and f.armors[ArmorType.PLATE] == 0)
    assert f.weapons[WeaponType.BOW] == 1
    assert f.armors[ArmorType.PLATE] == 0
    assert f.gold == 350 + 2500
    assert f.weapon == WeaponType.EXOTIC and f.armor == ArmorType.EXOTIC


def test_selling_waits_for_the_way_out(assets, monkeypatch):
    """The check runs when the town's errands are done: a party here for
    food buys its food, it doesn't sell first."""
    party = _endgame_party()
    _, f = _by_prof(party, Profession.FIGHTER)
    f.weapons[WeaponType.BOW] = 1
    sm, ts = _in_grey(assets, monkeypatch, party)
    ctrl = AutoPlayController(enabled=True)
    calls = []
    real = AutoPlayController._sell_spare_gear
    monkeypatch.setattr(
        AutoPlayController, "_sell_spare_gear",
        lambda self, *a, **k: calls.append(1) or real(self, *a, **k),
    )
    monkeypatch.setattr(AutoPlayController, "_maybe_manage_gear", lambda *a, **k: pygame.K_SPACE)
    ctrl.step(sm)  # an errand (stand-in) answers first
    assert calls == []


def test_no_selling_in_an_emergency(assets, monkeypatch):
    party = _endgame_party()
    _, f = _by_prof(party, Profession.FIGHTER)
    f.weapons[WeaponType.BOW] = 1
    party.members[0].food = 0
    sm, ts = _in_grey(assets, monkeypatch, party)
    ctrl = AutoPlayController(enabled=True)
    assert ctrl._sell_spare_gear(sm, ts, ts.game_map, party, 6, 29, 43, set()) is None


def test_no_selling_outside_shop_towns(assets, monkeypatch):
    party = _endgame_party()
    _, f = _by_prof(party, Profession.FIGHTER)
    f.weapons[WeaponType.BOW] = 1
    sm, ts = _in_grey(assets, monkeypatch, party)
    ctrl = AutoPlayController(enabled=True)
    assert ctrl._sell_spare_gear(sm, ts, ts.game_map, party, 4, 29, 43, set()) is None  # Yew


def test_a_sale_past_9999_gold_is_not_offered(assets, monkeypatch):
    party = _endgame_party()
    _, f = _by_prof(party, Profession.FIGHTER)
    f.armors[ArmorType.PLATE] = 1
    f.gold = 9800
    sm, ts = _in_grey(assets, monkeypatch, party, at=(35, 44))
    ctrl = AutoPlayController(enabled=True)
    assert ctrl._sell_spare_gear(sm, ts, ts.game_map, party, 6, 35, 44, set()) is None


def test_overworld_never_heads_for_a_shop_to_sell(assets, monkeypatch):
    """Spare gear is no goal: the planner's answer doesn't change."""
    from py_exodus.autoplay.planner import evaluate_goal

    party = _endgame_party()
    before = evaluate_goal(party, 0)
    _, f = _by_prof(party, Profession.FIGHTER)
    f.weapons[WeaponType.BOW] = 3
    f.armors[ArmorType.PLATE] = 2
    assert evaluate_goal(party, 0) == before
