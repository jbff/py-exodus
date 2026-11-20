"""Regression tests for Phase 0 EV/utility goal scoring in planner.py."""
from __future__ import annotations

from types import SimpleNamespace

from py_exodus.autoplay.planner import Goal, evaluate_goal, score_goals
from py_exodus.constants import ArmorType, Profession, Race, Status, Transport, WeaponType
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party


def _make_ev_party(
    *,
    level: int = 10,
    gold: int = 100,
    food: int = 500,
    marks: list[int] | None = None,
    cards: list[int] | None = None,
    exotics: bool = True,
    transport: Transport = Transport.FOOT,
) -> Party:
    p = Party()
    specs = [
        ("SHADOW", Race.ELF, Profession.THIEF),
        ("GRUMM", Race.DWARF, Profession.FIGHTER),
        ("SERENA", Race.BOBIT, Profession.CLERIC),
        ("ZIRCON", Race.FUZZY, Profession.WIZARD),
    ]
    per_gold = gold // 4
    rem_gold = gold % 4
    for i, (name, race, prof) in enumerate(specs):
        m = Character(name, "M", race, prof, gold=per_gold + (rem_gold if i == 0 else 0), food=food)
        m.level = level
        m.hp = m.max_hp = level * 100
        if marks is not None:
            m.marks = list(marks)
        if cards is not None and i == 0:
            m.cards = list(cards)
        if exotics:
            m.weapon = WeaponType.EXOTIC
            m.weapons[WeaponType.EXOTIC] = 1
            m.armor = ArmorType.EXOTIC
            m.armors[ArmorType.EXOTIC] = 1
        p.add_member(m)
    p.transport = transport
    return p


def test_ev_zero_food_scores_buy_food_highest():
    p = _make_ev_party(gold=100, food=0)
    assert evaluate_goal(p, map_id=0) == Goal.BUY_FOOD


def test_ev_poisoned_scores_cure_poison_above_grind():
    p = _make_ev_party(gold=200, food=500, marks=[1, 1, 1, 1])
    p.members[0].status = Status.POISONED
    scores = score_goals(p, map_id=0)
    assert scores[Goal.CURE_POISON] > scores[Goal.GRIND_AND_LEVEL]


def test_ev_dead_member_scores_resurrect_above_grind():
    p = _make_ev_party(gold=600, food=500, marks=[1, 1, 1, 1])
    p.members[0].status = Status.DEAD
    p.members[0].hp = 0
    scores = score_goals(p, map_id=0)
    assert scores[Goal.RESURRECT_DEAD] > scores[Goal.GRIND_AND_LEVEL]


def test_ev_endgame_ready_scores_conquer_exodus_highest():
    p = _make_ev_party(level=25, gold=500, food=500, marks=[1, 1, 1, 1], cards=[1, 1, 1, 1])
    assert evaluate_goal(p, map_id=0) == Goal.CONQUER_EXODUS


def test_ev_ambrosia_ready_on_ship_scores_sail_whirlpool_highest():
    p = _make_ev_party(
        level=15, gold=4500, food=500, marks=[1, 1, 1, 1], cards=[0, 0, 0, 0], transport=Transport.SHIP,
    )
    p.members[0].keys = 4
    assert evaluate_goal(p, map_id=0) == Goal.SAIL_WHIRLPOOL


def test_ev_dawn_open_increases_buy_keys_score():
    p = _make_ev_party(level=15, gold=500, food=500, marks=[1, 1, 1, 1], cards=[0, 0, 0, 0])
    open_scr = SimpleNamespace(trammel_phase=0, felucca_phase=0, creatures=[], game_map=None)
    closed_scr = SimpleNamespace(trammel_phase=3, felucca_phase=1, creatures=[], game_map=None)
    assert score_goals(p, map_id=0, screen=open_scr)[Goal.BUY_KEYS] > score_goals(p, map_id=0, screen=closed_scr)[Goal.BUY_KEYS]
