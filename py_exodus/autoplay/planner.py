"""Milestone goal evaluator and survival helpers for Full Autoplay."""
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from py_exodus.autoplay.equipment import (
    best_owned_armor,
    best_owned_weapon,
    best_shop_upgrade,
)
from py_exodus.constants import ArmorType, Profession, Status, Transport, WeaponType

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


def needs_food(party: Party) -> bool:
    """Return True if the party's LIVING members are running low on food.

    Rations are consumed per living member, and a dead member's pouches are
    not eaten. Counting them (or their zeroed pouches) made crippled parties
    look permanently starving: BUY_FOOD (900) outranked RESURRECT_DEAD (850)
    and GRIND (830) forever, so every coin went on food and no one was ever
    raised. Seed 203 on the fixed transport layer ended at the 160k step cap
    exactly so: three dead, 43 gold, the survivor carrying 150 food.
    """
    living = [m for m in party.members if not m.is_dead()]
    if not living:
        return False
    # 75 rations per living member is the same four-member reserve (300)
    # the ladder has always used, scaled to who actually eats.
    if sum(m.food for m in living) < 75 * len(living):
        return True
    return any(m.food < 75 for m in living)


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


def score_goals(
    party: Party,
    map_id: int | str | None = None,
    screen=None,
) -> dict[Goal, float]:
    """Compute EV/utility scores over all candidate progression Goals.

    Uses ``extract_macro_features`` so Phase 0 EV scoring and the Phase 3
    macro critic share the exact same feature representation.
    """
    from py_exodus.autoplay.features import extract_macro_features

    scores: dict[Goal, float] = {g: -1e9 for g in Goal}
    feats = extract_macro_features(party, map_id=map_id, screen=screen)

    if feats["exodus_done"] > 0.0:
        scores[Goal.DONE] = 1000.0
        return scores

    if feats["member_count"] < 4.0 or feats["living_count"] <= 0.0:
        scores[Goal.SETUP_PARTY] = 950.0
        return scores

    cur_map_id = int(feats["cur_map_id"])
    living = [m for m in party.members if not m.is_dead()]
    on_ship = feats["on_ship"] > 0.0
    at_exotic_island = feats["at_exotic_island"] > 0.0
    has_exotics = (
        feats["exotics_weapons_ratio"] >= 1.0 and feats["exotics_armor_ratio"] >= 1.0
    )
    living_has_exotics = all(
        (m.weapon == WeaponType.EXOTIC or m.weapons.get(WeaponType.EXOTIC, 0) > 0)
        and (m.armor == ArmorType.EXOTIC or m.armors.get(ArmorType.EXOTIC, 0) > 0)
        for m in living
    )
    in_dungeon_or_ambrosia = cur_map_id in (13, 15, 16, 17, 18, 19, 20)
    cannon_risk = 15.0 if (on_ship and feats["ship_hull"] <= 30.0) else 0.0
    pirate_risk = 10.0 if (on_ship and feats["nearest_pirate_dist"] <= 2.0) else 0.0
    dawn_bonus = 20.0 if feats["dawn_open"] > 0.0 else 0.0

    # 1. Sustenance & food runway
    # 2026-11-20 live trace (the Yew shuttle): needs_food() satisfied at the
    # ~25-pack reserve, so the ladder flipped to GRIND after each tiny
    # purchase and the party walked out, drained on the road, walked back -
    # buying ~25 per visit forever. The BUY_FOOD goal now fills to the
    # shop-target reserve (150) in ONE visit: hungry OR below the practical
    # stock threshold with coin available.
    food_below_stock = feats["min_member_food"] < 150.0 and feats["party_gold"] >= 150.0
    if (
        not in_dungeon_or_ambrosia
        and (
            not on_ship
            or (
                cur_map_id == 0
                and (feats["total_food"] < 250.0 or feats["min_member_food"] < 50.0)
                and not (at_exotic_island and not living_has_exotics)
            )
        )
        and (needs_food(party) or food_below_stock)
        and not (at_exotic_island and not living_has_exotics and feats["total_food"] >= 100.0)
        and (
            feats["party_gold"] >= 30.0
            or (food_below_stock and feats["party_gold"] >= 30.0)
        )
    ):
        starvation_urgency = max(0.0, 40.0 - min(40.0, feats["food_runway_turns"] * 0.1))
        scores[Goal.BUY_FOOD] = 900.0 + starvation_urgency + cannon_risk + pirate_risk

    # 2. Casualty & poison survival utility
    if (
        not in_dungeon_or_ambrosia
        and (not on_ship or cur_map_id == 0)
        and not (at_exotic_island and not living_has_exotics and feats["total_food"] >= 100.0)
        and any(m.is_dead() for m in party.members)
    ):
        if any(m.status == Status.POISONED and m.hp <= 25 for m in living) and feats["party_gold"] >= 100.0:
            scores[Goal.CURE_POISON] = 860.0 + cannon_risk
        needed_cost = min(
            (900 if m.status == Status.ASH else 500)
            for m in party.members
            if m.is_dead()
        )
        if feats["party_gold"] >= needed_cost:
            scores[Goal.RESURRECT_DEAD] = 850.0 + cannon_risk
        elif any(m.status == Status.POISONED for m in living) and feats["party_gold"] >= 100.0:
            scores[Goal.CURE_POISON] = 840.0
        else:
            scores[Goal.GRIND_AND_LEVEL] = 830.0

    if (
        not in_dungeon_or_ambrosia
        and not on_ship
        and not (at_exotic_island and not has_exotics and feats["total_food"] >= 100.0)
        and feats["poisoned_count"] > 0.0
        and feats["party_gold"] >= 100.0
    ):
        scores[Goal.CURE_POISON] = max(scores[Goal.CURE_POISON], 840.0)

    has_all_cards = int(feats["cards_mask"]) == 0xF
    has_remaining_marks = (int(feats["marks_mask"]) & 0b1110) == 0b1110

    # 3. Ambrosia shrines & cards
    if cur_map_id == 13:
        has_key = feats["total_keys"] > 0.0
        needs_key_card = any(not any(m.cards[idx] > 0 for m in living) for idx in (0, 2))
        # Cards 1/3 are collectable WITHOUT keys: free work a broke party
        # should still do before exiting.
        free_card_remains = any(
            not any(m.cards[idx] > 0 for m in living) for idx in (1, 3)
        )
        if (
            max(m.level for m in living) < 5
            or not all(m.marks[0] > 0 for m in party.members)
            or feats["total_food"] < 150.0
            or feats["min_member_food"] < 40.0
            or (not has_all_cards and needs_key_card and not has_key)
            or (has_all_cards and not needs_shrine_stats(party))
            # Broke and nothing free remains: exit rather than stall at an
            # unpayable shrine or key vendor. Free card sites stay open.
            or (
                feats["party_gold"] < 100.0
                and not (
                    (not has_all_cards and free_card_remains)
                )
            )
        ):
            scores[Goal.EXIT_AMBROSIA] = 760.0
        else:
            scores[Goal.AMBROSIA_CARDS_SHRINES] = 750.0

    # 4. Britain/Dawn equipment outfitting
    prefer_ranged = not (has_all_cards and has_remaining_marks and has_exotics)
    if (
        cur_map_id != 13
        and not on_ship
        and not (at_exotic_island and not has_exotics)
        and not (has_all_cards and has_remaining_marks and not has_exotics)
        and (
            best_shop_upgrade(party) is not None
            or any(
                best_owned_weapon(m, prefer_ranged=prefer_ranged) is not None
                or best_owned_armor(m) is not None
                for m in living
            )
        )
    ):
        scores[Goal.OUTFIT_BRITAIN] = 700.0 + dawn_bonus

    # 5. Early leveling, Marks, Exotics, Ambrosia prep, Exodus
    if feats["min_level"] < 5.0:
        scores[Goal.GRIND_AND_LEVEL] = max(scores[Goal.GRIND_AND_LEVEL], 680.0)

    if not all(m.marks[0] > 0 for m in party.members):
        if not in_dungeon_or_ambrosia and not on_ship:
            gems = feats["total_gems"]
            torches = feats["total_torches"]
            if gems < 2.0 and feats["party_gold"] >= (125.0 if gems == 0.0 else 200.0):
                scores[Goal.BUY_GEMS] = 660.0
            if torches < 4.0 and feats["party_gold"] >= (80.0 if torches == 0.0 else 150.0):
                scores[Goal.BUY_TORCHES] = 655.0
        scores[Goal.GET_MARK_KINGS] = 650.0

    if not has_exotics:
        if on_ship or at_exotic_island:
            scores[Goal.DIG_EXOTICS] = 610.0 - cannon_risk
        else:
            scores[Goal.CAPTURE_SHIP] = 605.0

    if not has_remaining_marks:
        if not in_dungeon_or_ambrosia and not on_ship:
            gems = feats["total_gems"]
            torches = feats["total_torches"]
            if gems < 8.0 and feats["party_gold"] >= (125.0 if gems == 0.0 else 225.0):
                scores[Goal.BUY_GEMS] = max(scores[Goal.BUY_GEMS], 570.0)
            if torches < 4.0 and feats["party_gold"] >= (80.0 if torches == 0.0 else 150.0):
                scores[Goal.BUY_TORCHES] = max(scores[Goal.BUY_TORCHES], 565.0)
        scores[Goal.GET_REMAINING_MARKS] = 550.0

    if not has_all_cards:
        if not on_ship and feats["total_keys"] < 4.0 and feats["party_gold"] >= 50.0:
            scores[Goal.BUY_KEYS] = 520.0 + dawn_bonus
        # User strategy ruling (2026-11-20): the FIRST Ambrosia trip happens
        # EARLY - just enough gold for 10 x 100g cleric-wis shrine points
        # (ALCORT costs 35 MP and MP = wisdom, so wis 35 buys self-sufficient
        # poison cures) plus keys - not after a 4500g stat-max grind. The
        # 4500 target only applies once the cleric can cast ALCORT, at which
        # point DG raids + Ambrosia stat-max returns become the loop.
        cleric_alcort_ready = any(
            not m.is_dead()
            and m.profession in (Profession.CLERIC, Profession.DRUID)
            and m.max_mp >= 35.0
            for m in party.members
        )
        if not cleric_alcort_ready:
            gold_target = 1500.0
        else:
            gold_target = 4500.0 if feats["any_below_shrine_cap"] > 0.0 else 1500.0
        if feats["living_count"] < feats["member_count"] or feats["party_gold"] < gold_target:
            scores[Goal.GRIND_AND_LEVEL] = max(scores[Goal.GRIND_AND_LEVEL], 510.0)
        needed_keys = sum(1 for idx in (0, 2) if not any(m.cards[idx] > 0 for m in living))
        if needed_keys > 0 and feats["total_keys"] < needed_keys:
            if feats["party_gold"] >= 50.0:
                scores[Goal.BUY_KEYS] = max(scores[Goal.BUY_KEYS], 505.0 + dawn_bonus)
            else:
                scores[Goal.GRIND_AND_LEVEL] = max(scores[Goal.GRIND_AND_LEVEL], 505.0)
        if (feats["total_food"] < 500.0 or feats["min_member_food"] < 120.0) and feats["party_gold"] >= 100.0:
            scores[Goal.BUY_FOOD] = max(scores[Goal.BUY_FOOD], 502.0)
        if not on_ship:
            scores[Goal.CAPTURE_SHIP] = max(scores[Goal.CAPTURE_SHIP], 501.0)
        scores[Goal.SAIL_WHIRLPOOL] = 500.0 - cannon_risk

    # Return Ambrosia trips (user doctrine, 2026-11-20): after the cards are
    # done, members below shrine cap go BACK for stats once gold supports a
    # visit (~100g/point + margin) - the first trip collected the cards; the
    # return trips are the stat-max loop. Broke-in-Ambrosia exits instead of
    # stalling at an unpayable shrine.
    if (
        has_all_cards
        and has_remaining_marks
        and feats["any_below_shrine_cap"] > 0.0
        and feats["party_gold"] >= 2000.0
    ):
        # 2026-11-20 live bug: this fired with the party ON FOOT after the
        # Ambrosia exit - "sail to the whirlpool" from grass is unreachable,
        # so the party idled. Grab a frigate first, then sail.
        if feats["on_ship"] > 0.0:
            scores[Goal.SAIL_WHIRLPOOL] = max(scores[Goal.SAIL_WHIRLPOOL], 470.0)
        else:
            scores[Goal.CAPTURE_SHIP] = max(scores[Goal.CAPTURE_SHIP], 506.0)

    if cur_map_id != 12 and feats["min_level"] < 25.0:
        scores[Goal.GRIND_AND_LEVEL] = max(scores[Goal.GRIND_AND_LEVEL], 450.0)

    scores[Goal.CONQUER_EXODUS] = 400.0
    return scores


def evaluate_goal(party: Party, map_id: int | str | None = None) -> Goal:
    """Inspect live Party state and return the highest-EV progression milestone."""
    scores = score_goals(party, map_id=map_id)
    return max(scores, key=scores.__getitem__)
