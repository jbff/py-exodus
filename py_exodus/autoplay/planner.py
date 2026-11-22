"""Milestone goal evaluator and survival helpers for Full Autoplay."""
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from py_exodus.autoplay.equipment import (
    best_owned_armor,
    best_owned_weapon,
    best_shop_upgrade,
)
from py_exodus.constants import ArmorType, Profession, Status, WeaponType

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
    SAIL_WHIRLPOOL = "sail_whirlpool"
    AMBROSIA_CARDS_SHRINES = "ambrosia_cards_shrines"
    EXIT_AMBROSIA = "exit_ambrosia"
    GET_REMAINING_MARKS = "get_remaining_marks"
    DIG_EXOTICS = "dig_exotics"
    CONQUER_EXODUS = "conquer_exodus"
    DONE = "done"


def needs_heal(party: Party) -> bool:
    """Return True if any living member is below 85% HP or poisoned and missing HP."""
    for m in party.members:
        if not m.is_dead() and m.max_hp > 0 and (
            m.hp * 20 < m.max_hp * 17 or (m.status == Status.POISONED and m.hp + 30 < m.max_hp)
        ):
            return True
    return False


def needs_cure(party: Party) -> bool:
    """Return True if any member is poisoned, dead, or ashes."""
    for m in party.members:
        if m.status in (Status.POISONED, Status.DEAD, Status.ASH):
            return True
    return False


# Ambrosia budget (user rule 2026-11-21: never go there about to starve;
# abort for food in time). Surface eating is 1 food per member every 10
# moves (Party.consume_food, decr_interval 40 vs 400 submorsels); a visit
# runs ~1500-2500 moves, and finding a pirate and sailing out ~500-800.
AMBROSIA_ENTRY_FOOD = 300
AMBROSIA_ABORT_FOOD = 80
# Keys beyond the card doors: the door east of the arrival point and the
# water door between the east basin and the whirlpool bay.
AMBROSIA_SPARE_KEYS = 2


def needs_food(party: Party) -> bool:
    """Return True if party food supply or any living member's food is low."""
    if party.food < 300:
        return True
    return any(not m.is_dead() and m.food < 75 for m in party.members)


_CLERIC_CASTERS = (Profession.CLERIC, Profession.DRUID, Profession.PALADIN, Profession.RANGER)
_WIZARD_CASTERS = (
    Profession.WIZARD,
    Profession.DRUID,
    Profession.ALCHEMIST,
    Profession.ILLUSIONIST,
    Profession.LARK,
)


def member_needs_shrine_stat(member, stat_attr: str, cap_attr: str) -> bool:
    """Return True if this living member should raise ``stat_attr`` at an Ambrosia Shrine."""
    if member.is_dead():
        return False
    prof = getattr(member, "profession", None)
    if stat_attr == "wisdom" and prof not in _CLERIC_CASTERS:
        return False
    if stat_attr == "intelligence" and prof not in _WIZARD_CASTERS:
        return False
    return getattr(member, stat_attr, 0) < getattr(member, cap_attr, 99)


def needs_shrine_stats(party: Party) -> bool:
    """Return True if party has >= 500g and any living member still needs a relevant Shrine stat."""
    if party.gold < 500:
        return False
    return any(
        member_needs_shrine_stat(m, stat_attr, cap_attr)
        for m in party.members
        for stat_attr, cap_attr in (
            ("strength", "max_str"),
            ("dexterity", "max_dex"),
            ("wisdom", "max_wis"),
            ("intelligence", "max_int"),
        )
    )


def _normalize_map_id(party: Party, map_id: int | str | None) -> int:
    raw_map = party.map_id if map_id is None else map_id
    if isinstance(raw_map, str) and raw_map.lower() == "ambrosia":
        return 13
    try:
        return int(raw_map)
    except (TypeError, ValueError):
        return party.map_id


def prefer_ranged_weapons(party: Party) -> bool:
    """Return True until the party has all 4 cards, remaining marks, and exotics."""
    living = [m for m in party.members if not m.is_dead()]
    if not living:
        return True
    has_all_cards = all(any(m.cards[i] > 0 for m in living) for i in range(4))
    has_remaining_marks = all(any(m.marks[i] > 0 for m in living) for i in (1, 2, 3))
    has_exotics = all(
        (m.weapon == WeaponType.EXOTIC or m.weapons.get(WeaponType.EXOTIC, 0) > 0)
        and (m.armor == ArmorType.EXOTIC or m.armors.get(ArmorType.EXOTIC, 0) > 0)
        for m in party.members
    )
    return not (has_all_cards and has_remaining_marks and has_exotics)


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

    # Goals never depend on the transport mode: the trip layer
    # (autoplay/trip.py) decides walking, sailing, capturing or moongates, so
    # boarding or landing can never flip the goal (the old B/X loops).
    at_exotic_island = (
        cur_map_id == 0
        and any(abs(party.x - tx) + abs(party.y - ty) <= 4 for tx, ty in ((33, 3), (19, 44)))
    )
    has_exotics = all(
        (m.weapon == WeaponType.EXOTIC or m.weapons.get(WeaponType.EXOTIC, 0) > 0)
        and (m.armor == ArmorType.EXOTIC or m.armors.get(ArmorType.EXOTIC, 0) > 0)
        for m in party.members
    )
    living_has_exotics = all(
        (m.weapon == WeaponType.EXOTIC or m.weapons.get(WeaponType.EXOTIC, 0) > 0)
        and (m.armor == ArmorType.EXOTIC or m.armors.get(ArmorType.EXOTIC, 0) > 0)
        for m in living
    )

    if (
        cur_map_id not in (13, 15, 16, 17, 18, 19, 20)
        and needs_food(party)
        and not (at_exotic_island and not living_has_exotics and party.food >= 100)
        and party.gold >= 30
    ):
        return Goal.BUY_FOOD

    if (
        cur_map_id not in (13, 15, 16, 17, 18, 19, 20)
        and not (at_exotic_island and not living_has_exotics and party.food >= 100)
        and any(m.is_dead() for m in party.members)
    ):
        if any(m.status == Status.POISONED and m.hp <= 25 for m in living) and party.gold >= 100:
            return Goal.CURE_POISON
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
        and not (at_exotic_island and not living_has_exotics and party.food >= 100)
        and any(m.status == Status.POISONED for m in living)
        and party.gold >= 100
    ):
        return Goal.CURE_POISON

    has_all_cards = all(any(m.cards[i] > 0 for m in living) for i in range(4))
    has_remaining_marks = all(any(m.marks[i] > 0 for m in living) for i in (1, 2, 3))

    if cur_map_id == 13:
        has_key = any(m.keys > 0 for m in living)
        needs_key_card = any(not any(m.cards[idx] > 0 for m in living) for idx in (0, 2))
        if (
            max(m.level for m in living) < 5
            or not all(m.marks[0] > 0 for m in party.members)
            or any(m.food < AMBROSIA_ABORT_FOOD for m in living)
            or (not has_all_cards and needs_key_card and not has_key)
            or (has_all_cards and not needs_shrine_stats(party))
        ):
            return Goal.EXIT_AMBROSIA
        return Goal.AMBROSIA_CARDS_SHRINES

    prefer_ranged = not (has_all_cards and has_remaining_marks and has_exotics)
    if (
        cur_map_id != 13
        and not (at_exotic_island and not living_has_exotics)
        and not (has_all_cards and has_remaining_marks and not living_has_exotics)
        and (
            best_shop_upgrade(party) is not None
            or any(
                best_owned_weapon(m, prefer_ranged=prefer_ranged) is not None
                or best_owned_armor(m) is not None
                for m in living
            )
        )
    ):
        return Goal.OUTFIT_BRITAIN

    if min(m.level for m in living) < 5:
        return Goal.GRIND_AND_LEVEL

    if not all(m.marks[0] > 0 for m in party.members):
        if cur_map_id not in (13, 15, 16, 17, 18, 19, 20):
            gems = sum(m.gems for m in living)
            torches = sum(m.torches for m in living)
            if gems < 2 and party.gold >= (125 if gems == 0 else 200):
                return Goal.BUY_GEMS
            if torches < 4 and party.gold >= (80 if torches == 0 else 150):
                return Goal.BUY_TORCHES
        return Goal.GET_MARK_KINGS

    # Living members only: the dead can't dig (or use) them, and a party with
    # dead members and no gold for a healer must not loop at the dig site.
    if not living_has_exotics:
        return Goal.DIG_EXOTICS

    if not has_remaining_marks:
        if cur_map_id not in (13, 15, 16, 17, 18, 19, 20):
            gems = sum(m.gems for m in living)
            torches = sum(m.torches for m in living)
            if gems < 8 and party.gold >= (125 if gems == 0 else 225):
                return Goal.BUY_GEMS
            if torches < 4 and party.gold >= (80 if torches == 0 else 150):
                return Goal.BUY_TORCHES
        return Goal.GET_REMAINING_MARKS

    if not has_all_cards:
        if cur_map_id == 13:
            return Goal.AMBROSIA_CARDS_SHRINES
        if sum(m.keys for m in living) < 4 and party.gold >= 50:
            return Goal.BUY_KEYS
        any_below_cap = any(
            member_needs_shrine_stat(m, stat_attr, cap_attr)
            for m in living
            for stat_attr, cap_attr in (
                ("strength", "max_str"),
                ("dexterity", "max_dex"),
                ("wisdom", "max_wis"),
                ("intelligence", "max_int"),
            )
        )
        gold_target = 4500 if any_below_cap else 1500
        if len(living) < len(party.members) or party.gold < gold_target:
            return Goal.GRIND_AND_LEVEL
        needed_keys = sum(
            1 for idx in (0, 2) if not any(m.cards[idx] > 0 for m in living)
        )
        if sum(m.keys for m in living) < needed_keys + AMBROSIA_SPARE_KEYS:
            if party.gold >= 50:
                return Goal.BUY_KEYS
            return Goal.GRIND_AND_LEVEL
        if any(m.food < AMBROSIA_ENTRY_FOOD for m in living):
            if party.gold >= 100:
                return Goal.BUY_FOOD
            return Goal.GRIND_AND_LEVEL  # earn it; never sail in hungry
        return Goal.SAIL_WHIRLPOOL

    if cur_map_id == 13:
        if needs_shrine_stats(party):
            return Goal.AMBROSIA_CARDS_SHRINES
        return Goal.EXIT_AMBROSIA

    if cur_map_id != 12 and min(m.level for m in living) < 25:
        return Goal.GRIND_AND_LEVEL

    return Goal.CONQUER_EXODUS
