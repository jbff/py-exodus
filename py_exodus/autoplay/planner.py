"""Milestone goal evaluator and survival helpers for Full Autoplay."""
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from py_exodus.constants import ArmorType, Status, Transport, WeaponType

if TYPE_CHECKING:
    from py_exodus.entities.party import Party


class Goal(str, Enum):
    """High-level Ultima III progression milestones."""

    SETUP_PARTY = "setup_party"
    OUTFIT_BRITAIN = "outfit_britain"
    GRIND_AND_LEVEL = "grind_and_level"
    GET_MARK_KINGS = "get_mark_kings"
    CAPTURE_SHIP = "capture_ship"
    SAIL_WHIRLPOOL = "sail_whirlpool"
    AMBROSIA_CARDS_SHRINES = "ambrosia_cards_shrines"
    EXIT_AMBROSIA = "exit_ambrosia"
    GET_REMAINING_MARKS = "get_remaining_marks"
    DIG_EXOTICS = "dig_exotics"
    CONQUER_EXODUS = "conquer_exodus"
    DONE = "done"


def needs_heal(party: Party) -> bool:
    """Return True if any living member is below 67% HP."""
    for m in party.members:
        if not m.is_dead() and m.max_hp > 0 and m.hp * 3 < m.max_hp * 2:
            return True
    return False


def needs_cure(party: Party) -> bool:
    """Return True if any member is poisoned, dead, or ashes."""
    for m in party.members:
        if m.status in (Status.POISONED, Status.DEAD, Status.ASH):
            return True
    return False


def needs_food(party: Party) -> bool:
    """Return True if party food supply is critically low."""
    return party.food < 100


def evaluate_goal(party: Party) -> Goal:
    """Inspect live Party state and return the active progression milestone."""
    if getattr(party, "exodus_defeated", 0) > 0 or getattr(party, "exodus_cards_status", 0) == 0xF:
        return Goal.DONE

    if not party.members or len(party.members) < 4:
        return Goal.SETUP_PARTY

    living = [m for m in party.members if not m.is_dead()]
    if not living:
        return Goal.SETUP_PARTY

    if (
        min(m.level for m in living) < 2
        and any(
            (m.weapon == WeaponType.NONE and m.gold >= 5)
            or (m.armor == ArmorType.NONE and m.gold >= 75)
            or (
                m.weapon == WeaponType.NONE
                and any(cnt > 0 for w, cnt in m.weapons.items() if w != WeaponType.NONE)
            )
            or (
                m.armor == ArmorType.NONE
                and any(cnt > 0 for a, cnt in m.armors.items() if a != WeaponType.NONE)
            )
            for m in living
        )
    ):
        return Goal.OUTFIT_BRITAIN

    if min(m.level for m in living) < 5:
        return Goal.GRIND_AND_LEVEL

    if not all(m.marks[0] > 0 for m in living):
        return Goal.GET_MARK_KINGS

    has_all_cards = all(any(m.cards[i] > 0 for m in living) for i in range(4))
    if not has_all_cards:
        if party.map_id == 13:
            return Goal.AMBROSIA_CARDS_SHRINES
        if party.transport != Transport.SHIP:
            return Goal.CAPTURE_SHIP
        return Goal.SAIL_WHIRLPOOL

    if party.map_id == 13:
        return Goal.EXIT_AMBROSIA

    has_remaining_marks = all(any(m.marks[i] > 0 for m in living) for i in (1, 2, 3))
    if not has_remaining_marks:
        return Goal.GET_REMAINING_MARKS

    has_exotics = all(
        m.weapons.get(WeaponType.EXOTIC, 0) > 0 and m.armors.get(ArmorType.EXOTIC, 0) > 0
        for m in living
    )
    if not has_exotics:
        return Goal.DIG_EXOTICS

    return Goal.CONQUER_EXODUS
