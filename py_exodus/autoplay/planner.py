"""Milestone goal evaluator and survival helpers for Full Autoplay."""
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from py_exodus.autoplay.equipment import (
    best_owned_armor,
    best_owned_weapon,
    best_shop_upgrade,
)
from py_exodus.constants import ArmorType, Status, Transport, WeaponType

if TYPE_CHECKING:
    from py_exodus.entities.party import Party


class Goal(str, Enum):
    """High-level Ultima III progression milestones."""

    SETUP_PARTY = "setup_party"
    BUY_FOOD = "buy_food"
    RESURRECT_DEAD = "resurrect_dead"
    CURE_POISON = "cure_poison"
    OUTFIT_BRITAIN = "outfit_britain"
    GRIND_AND_LEVEL = "grind_and_level"
    BUY_GEMS = "buy_gems"
    BUY_TORCHES = "buy_torches"
    GET_MARK_KINGS = "get_mark_kings"
    BUY_KEYS = "buy_keys"
    CAPTURE_SHIP = "capture_ship"
    SAIL_WHIRLPOOL = "sail_whirlpool"
    AMBROSIA_CARDS_SHRINES = "ambrosia_cards_shrines"
    EXIT_AMBROSIA = "exit_ambrosia"
    GET_REMAINING_MARKS = "get_remaining_marks"
    DIG_EXOTICS = "dig_exotics"
    CONQUER_EXODUS = "conquer_exodus"
    DONE = "done"


def needs_heal(party: Party) -> bool:
    """Return True if any living member is below 75% HP or poisoned and missing HP."""
    for m in party.members:
        if not m.is_dead() and m.max_hp > 0 and (
            m.hp * 4 < m.max_hp * 3 or (m.status == Status.POISONED and m.hp + 30 < m.max_hp)
        ):
            return True
    return False


def needs_cure(party: Party) -> bool:
    """Return True if any member is poisoned, dead, or ashes."""
    for m in party.members:
        if m.status in (Status.POISONED, Status.DEAD, Status.ASH):
            return True
    return False


def needs_food(party: Party) -> bool:
    """Return True if party food supply is low enough to warrant a bulk restock."""
    return party.food < 300


def _normalize_map_id(party: Party, map_id: int | str | None) -> int:
    raw_map = party.map_id if map_id is None else map_id
    if isinstance(raw_map, str) and raw_map.lower() == "ambrosia":
        return 13
    try:
        return int(raw_map)
    except (TypeError, ValueError):
        return party.map_id


def evaluate_goal(party: Party, map_id: int | str | None = None) -> Goal:
    """Inspect live Party state and return the active progression milestone."""
    if getattr(party, "exodus_defeated", 0) > 0 or getattr(party, "exodus_cards_status", 0) == 0xF:
        return Goal.DONE

    if not party.members or len(party.members) < 4:
        return Goal.SETUP_PARTY

    living = [m for m in party.members if not m.is_dead()]
    if not living:
        return Goal.SETUP_PARTY

    cur_map_id = _normalize_map_id(party, map_id)

    at_exotic_island = cur_map_id == 0 and any(
        abs(party.x - tx) + abs(party.y - ty) <= 2 for tx, ty in ((33, 3), (19, 44))
    )
    has_exotics = all(
        (m.weapon == WeaponType.EXOTIC or m.weapons.get(WeaponType.EXOTIC, 0) > 0)
        and (m.armor == ArmorType.EXOTIC or m.armors.get(ArmorType.EXOTIC, 0) > 0)
        for m in living
    )

    if (
        cur_map_id != 13
        and party.transport != Transport.SHIP
        and needs_food(party)
        and not (at_exotic_island and not has_exotics and party.food >= 100)
        and sum(m.gold for m in living) >= 30
    ):
        return Goal.BUY_FOOD

    if (
        cur_map_id not in (13, 15, 16, 17, 18, 19, 20)
        and party.transport != Transport.SHIP
        and any(m.is_dead() for m in party.members)
    ):
        needed_cost = min(
            (900 if m.status == Status.ASH else 500)
            for m in party.members
            if m.is_dead()
        )
        if party.gold >= needed_cost:
            return Goal.RESURRECT_DEAD
        if any(m.status == Status.POISONED for m in living) and party.gold >= 100:
            return Goal.CURE_POISON
        return Goal.GRIND_AND_LEVEL

    if (
        cur_map_id not in (13, 15, 16, 17, 18, 19, 20)
        and party.transport != Transport.SHIP
        and any(m.status == Status.POISONED for m in living)
        and party.gold >= 100
    ):
        return Goal.CURE_POISON

    has_all_cards = all(any(m.cards[i] > 0 for m in living) for i in range(4))
    has_remaining_marks = all(any(m.marks[i] > 0 for m in living) for i in (1, 2, 3))

    if cur_map_id == 0 and not has_exotics and (party.transport == Transport.SHIP or at_exotic_island):
        return Goal.DIG_EXOTICS

    if (
        cur_map_id != 13
        and party.transport != Transport.SHIP
        and not (has_all_cards and has_remaining_marks and not has_exotics)
        and (
            best_shop_upgrade(party) is not None
            or any(best_owned_weapon(m) is not None or best_owned_armor(m) is not None for m in living)
        )
    ):
        return Goal.OUTFIT_BRITAIN

    if max(m.level for m in living) < 5:
        return Goal.GRIND_AND_LEVEL

    if not all(m.marks[0] > 0 for m in party.members):
        if (
            cur_map_id not in (13, 15, 16, 17, 18, 19, 20)
            and party.transport != Transport.SHIP
        ):
            if sum(m.gems for m in living) < 2 and sum(m.gold for m in living) >= 75:
                return Goal.BUY_GEMS
            if sum(m.torches for m in living) < 4 and sum(m.gold for m in living) >= 30:
                return Goal.BUY_TORCHES
        return Goal.GET_MARK_KINGS

    if not has_all_cards:
        if cur_map_id == 13:
            return Goal.AMBROSIA_CARDS_SHRINES
        if (
            party.transport != Transport.SHIP
            and sum(m.keys for m in living) < 4
            and sum(m.gold for m in living) >= 50
        ):
            return Goal.BUY_KEYS
        if party.transport != Transport.SHIP:
            return Goal.CAPTURE_SHIP
        return Goal.SAIL_WHIRLPOOL

    if cur_map_id == 13:
        return Goal.EXIT_AMBROSIA

    if not has_remaining_marks:
        if (
            cur_map_id not in (13, 15, 16, 17, 18, 19, 20)
            and party.transport != Transport.SHIP
        ):
            if sum(m.gems for m in living) < 8 and sum(m.gold for m in living) >= 75:
                return Goal.BUY_GEMS
            if sum(m.torches for m in living) < 4 and sum(m.gold for m in living) >= 30:
                return Goal.BUY_TORCHES
        return Goal.GET_REMAINING_MARKS

    if not has_exotics:
        return Goal.DIG_EXOTICS

    return Goal.CONQUER_EXODUS
