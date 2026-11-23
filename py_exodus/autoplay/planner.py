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
AMBROSIA_ENTRY_FOOD = 200
AMBROSIA_SHRINE_BUDGET = 4500
AMBROSIA_ABORT_FOOD = 80
# A return trip for stats needs keys too. Doors relock between visits, and
# the live trace of 2026-11-22 spent up to 5 a visit: (45,17), (58,3),
# the water door (39,61), (50,6) chasing a pirate ship, (10,6) to the
# intelligence shrine. Budget for all of them plus spares. The last one is
# kept for the way out.
AMBROSIA_RETURN_KEYS = 8
AMBROSIA_EXIT_KEYS = 1
# A Death Gulch raid needs keys for its locked doors AND gold to bribe its
# guards (user 2026-11-22).
DEATH_GULCH_KEYS = 4
DEATH_GULCH_BRIBE_GOLD = 400
# Card trips budget the same 8 (user live trace 2026-11-22): the Moons card
# alone sits behind (45,17), (50,6) and (11,6), and the exit rule fires on
# the last key, so the old needed+2 budget (4 keys) turned back five tiles
# short of (6,6) on four visits running.
AMBROSIA_CARD_KEYS = AMBROSIA_RETURN_KEYS


def alcort_wisdom_gap(party: Party) -> int | None:
    """Wisdom points (100 gold each at the Ambrosia shrine) until a living
    Cleric/Druid can cast ALCORT (max MP 35: Cleric MP = WIS, Druid MP =
    max(INT, WIS) // 2). 0 = already able; None = nobody can get there."""
    gaps = []
    for m in party.members:
        if m.is_dead():
            continue
        if m.profession == Profession.CLERIC:
            need = 35
        elif m.profession == Profession.DRUID:
            need = 70
        else:
            continue
        if m.max_mp >= 35:
            return 0
        if stat_cap(m, "max_wis") >= need:
            gaps.append(max(0, need - m.wisdom))
    return min(gaps) if gaps else None


def ambrosia_trip_gold(party: Party, needed_keys: int = 0) -> int:
    """Gold the party should hold before sailing for Ambrosia.

    User ruling (2026-11-22): save the full shrine budget for the first
    trip. The early cheap ALCORT trip (2026-11-21) was for the poisoning,
    which turned out to be Death Gulch chest traps (now opened safely), and
    it bought only ~11 wisdom. The target also covers the food and keys
    still to buy, so buying them never drops the party back under it.
    """
    living = [m for m in party.members if not m.is_dead()]
    shrine_gold = AMBROSIA_SHRINE_BUDGET if next_shrine_goal(party) is not None else 1500
    food_gold = sum(max(0, AMBROSIA_ENTRY_FOOD - m.food) for m in living) * 6 // 5
    keys_short = max(0, AMBROSIA_CARD_KEYS - sum(m.keys for m in living))
    return shrine_gold + food_gold + 50 * keys_short


def needs_food(party: Party) -> bool:
    """Return True if party food supply or any living member's food is low."""
    if party.food < 300:
        return True
    return any(not m.is_dead() and m.food < 75 for m in party.members)


# Food a living member can run down to while the party saves for a
# resurrection: 1 food per 10 moves, so ~400 moves to earn the rest.
RESURRECT_FOOD_FLOOR = 40


def resurrection_cost(party: Party) -> int | None:
    """Gold for the cheapest dead member (500, or 900 for ashes); None if
    nobody is dead."""
    costs = [900 if m.status == Status.ASH else 500 for m in party.members if m.is_dead()]
    return min(costs) if costs else None


def saving_to_resurrect(party: Party) -> bool:
    """A member is dead and nobody living is about to starve: food waits for
    the resurrection (batch 775884a seed 3 spent 80 of 490 gold on food at
    74 each with the Cleric dead, and wiped). Bought first, food would also
    drop a party that can just afford the healer back under the price."""
    if resurrection_cost(party) is None:
        return False
    return all(m.food >= RESURRECT_FOOD_FLOOR for m in party.members if not m.is_dead())


# HP a poisoned member keeps in hand while the caster's MP comes back.
ALCORT_WAIT_MARGIN = 25


def alcort_coming(party: Party, map_id: int) -> bool:
    """A living Cleric/Druid whose MP pool reaches ALCORT's 35 will have the
    MP before any poisoned member runs low: skip the healer and cure on the
    spot (user 2026-11-22: a Cleric with WIS 35 walked the party to a
    healer). Surface MP returns 1 a turn (a Druid 2) against 1 HP of poison;
    off the surface, MP comes every 4th turn."""
    living = [m for m in party.members if not m.is_dead()]
    casters = [
        m for m in living
        if m.profession in (Profession.CLERIC, Profession.DRUID) and m.max_mp >= 35
    ]
    if not casters:
        return False
    surface = map_id in (0, 13)

    def turns(m) -> int:
        need = max(0, 35 - m.mp)
        rate = 2 if m.profession == Profession.DRUID else 1
        return -(-need // rate) * (1 if surface else 4)

    wait = min(turns(m) for m in casters)
    return all(
        m.hp > wait + ALCORT_WAIT_MARGIN for m in living if m.status == Status.POISONED
    )


_CLERIC_CASTERS = (Profession.CLERIC, Profession.DRUID, Profession.PALADIN, Profession.RANGER)
_WIZARD_CASTERS = (
    Profession.WIZARD,
    Profession.DRUID,
    Profession.ALCHEMIST,
    Profession.ILLUSIONIST,
    Profession.LARK,
)


def stat_cap(member, cap_attr: str) -> int:
    """The member's shrine cap for a stat: it belongs to the RACE
    (``Race.max_str`` etc.; Human 75, Bobbit WIS 99, Fuzzy INT 99...).
    Reading ``member.max_str`` (absent) defaulted every cap to 99, so a
    capped member kept paying 100 gold a point for nothing."""
    race = getattr(member, "race", None)
    cap = getattr(race, cap_attr, None) if race is not None else None
    if cap is None:
        cap = getattr(member, cap_attr, 99)
    return int(cap)


def member_needs_shrine_stat(member, stat_attr: str, cap_attr: str) -> bool:
    """Return True if this living member should raise ``stat_attr`` at an Ambrosia Shrine."""
    if member.is_dead():
        return False
    prof = getattr(member, "profession", None)
    if stat_attr == "wisdom" and prof not in _CLERIC_CASTERS:
        return False
    if stat_attr == "intelligence" and prof not in _WIZARD_CASTERS:
        return False
    return getattr(member, stat_attr, 0) < stat_cap(member, cap_attr)


# Shrine buying order (user request 2026-11-22), worked out from the code:
#  * Hit roll is rand(0..255) + bonus > 128 (monster defence is always 128),
#    and the bonus is 255 once DEX >= 40 (combat/resolver.py): DEX 15 hits
#    55%, DEX 40 always hits. DEX above 40 only helps dodge chest traps.
#  * Damage is 4..(weapon dmax + 1.5 * STR) (exotic dmax 49): about +0.75
#    average damage per STR point, half the value of DEX up to 40.
#  * Cleric MP = WIS, Wizard MP = INT; auto-combat casts SANCTU_MANI (50),
#    NOXUM (50), ZXKUQYB (70) and UNSPEAKABLE (75).
# Each step: (professions, stat, cap attr, target). A target above the
# race cap stops at the cap. 100 gold buys one point.
_MELEE_FIRST = (Profession.FIGHTER, Profession.BARBARIAN, Profession.PALADIN, Profession.RANGER)
_DEX_SECOND = (Profession.THIEF, Profession.LARK)
_HEALERS = (Profession.CLERIC,)
_MAGES = (Profession.WIZARD,)
_EVERYONE = tuple(Profession)
SHRINE_PLAN: tuple[tuple[tuple[Profession, ...], str, str, int], ...] = (
    # Healer WIS to the race cap first (user ruling 2026-11-22): ALCORT,
    # SANCTU_MANI and ZXKUQYB on the way, and the biggest APPAR UNEM pool,
    # so Death Gulch raids stop waiting for MP and every later trip comes
    # sooner.
    (_HEALERS, "wisdom", "max_wis", 99),
    ((Profession.DRUID,), "wisdom", "max_wis", 70),  # Druid MP = WIS // 2
    (_MELEE_FIRST, "dexterity", "max_dex", 40),      # always hit
    (_DEX_SECOND, "dexterity", "max_dex", 40),
    (_HEALERS, "dexterity", "max_dex", 40),
    (_MAGES, "dexterity", "max_dex", 40),
    (_EVERYONE, "dexterity", "max_dex", 40),
    (_MAGES, "intelligence", "max_int", 50),        # NOXUM (multi-fireball)
    (_MAGES, "intelligence", "max_int", 75),        # UNSPEAKABLE (multi-death bolt)
    (_MELEE_FIRST, "strength", "max_str", 99),      # damage
    (_DEX_SECOND, "strength", "max_str", 99),
    (_MAGES, "intelligence", "max_int", 99),
    # ---- return trips stop here: DEX 40 all, maxed caster MP (user ruling
    # 2026-11-22); the steps below are bought only with leftover gold.
    (_EVERYONE, "strength", "max_str", 99),
    (_DEX_SECOND, "dexterity", "max_dex", 74),      # chest traps: nicety only
)
SHRINE_RESERVE = 150  # gold kept back on every donation
# Steps worth a dedicated return trip to Ambrosia (through Wizard INT 99).
RETURN_TRIP_STEPS = 1 + next(
    i for i, (profs, stat, _c, t) in enumerate(SHRINE_PLAN)
    if profs == _MAGES and stat == "intelligence" and t == 99
)
RETURN_TRIP_MAX_GOLD = 9000  # one trip's budget cap (the Death Gulch raid cap)


def next_shrine_goal(party: Party, steps: int | None = None) -> tuple[int, str, str, int] | None:
    """First unmet step of SHRINE_PLAN (or of its first ``steps`` steps):
    (member index, stat, cap attr, target clamped to the member's race
    cap), or None when all are met."""
    for profs, stat_attr, cap_attr, target in SHRINE_PLAN[:steps]:
        for i, m in enumerate(party.members):
            if m.is_dead() or m.profession not in profs:
                continue
            goal = min(target, stat_cap(m, cap_attr))
            if getattr(m, stat_attr, 0) < goal:
                return (i, stat_attr, cap_attr, goal)
    return None


def return_trip_cost(party: Party) -> int:
    """Gold to finish the return-trip steps of SHRINE_PLAN (100 a point)."""
    stats = {
        (i, attr): getattr(m, attr, 0)
        for i, m in enumerate(party.members)
        for attr in ("strength", "dexterity", "intelligence", "wisdom")
    }
    cost = 0
    for profs, stat_attr, cap_attr, target in SHRINE_PLAN[:RETURN_TRIP_STEPS]:
        for i, m in enumerate(party.members):
            if m.is_dead() or m.profession not in profs:
                continue
            goal = min(target, stat_cap(m, cap_attr))
            if stats[(i, stat_attr)] < goal:
                cost += (goal - stats[(i, stat_attr)]) * 100
                stats[(i, stat_attr)] = goal
    return cost


def return_trip_gold(party: Party) -> int:
    """Gold to hold before a return trip for stats (all cards owned): the
    rest of the return-trip steps (at most one trip's cap) plus the reserve
    and the food still to buy. 0 when no return trip is wanted."""
    cost = return_trip_cost(party)
    if cost == 0:
        return 0
    living = [m for m in party.members if not m.is_dead()]
    food_gold = sum(max(0, AMBROSIA_ENTRY_FOOD - m.food) for m in living) * 6 // 5
    # The keys still to buy are in the target too, so buying them never
    # drops the party back under it (and back to raiding).
    keys_gold = 50 * max(0, AMBROSIA_RETURN_KEYS - sum(m.keys for m in living))
    extras = SHRINE_RESERVE + food_gold + keys_gold
    # The stats are capped by a FIXED amount that leaves room for the most
    # food and keys a trip can need, so the target stays below the raid cap
    # and buying keys or food lowers it exactly as much as the gold. (Capping
    # by the current extras held it at 8,500: one key at 50 dropped the party
    # under, back to raiding, which uses keys; batch ccd5f52 seeds 100, 101,
    # 105, 108 looped there for ~100,000 steps.)
    most_extras = (
        SHRINE_RESERVE
        + len(party.members) * AMBROSIA_ENTRY_FOOD * 6 // 5
        + 50 * AMBROSIA_RETURN_KEYS
    )
    return min(cost, RETURN_TRIP_MAX_GOLD - 500 - most_extras) + extras


def raid_gold_target(party: Party, cap: int) -> int:
    """Gold a Death Gulch raid stops at. On return trips for stats, just
    what the rest of the plan costs (user 2026-11-22: a party 1,100 gold
    short of its last INT points raided on to 8,500); otherwise ``cap``."""
    living = [m for m in party.members if not m.is_dead()]
    has_all_cards = all(any(m.cards[i] > 0 for m in living) for i in range(4))
    trip = return_trip_gold(party) if has_all_cards else 0
    return min(trip, cap) if trip else cap


def gold_has_a_use(party: Party) -> bool:
    """Raid for gold only while it will be spent: cards still to fetch, or
    return trips for stats still pending (user ruling 2026-11-22)."""
    living = [m for m in party.members if not m.is_dead()]
    has_all_cards = all(any(m.cards[i] > 0 for m in living) for i in range(4))
    return not has_all_cards or return_trip_cost(party) > 0


def needs_shrine_stats(party: Party) -> bool:
    """>= 500 gold (worth staying on Ambrosia for) and a plan step left."""
    if party.gold < 500:
        return False
    return next_shrine_goal(party) is not None


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
    # Town 12 (its only gate is (30, 2)) is on the (33, 3) island: inside it
    # counts as being there, or its goals differ from the gate's and the
    # party walks in and out (batch 8d3aef0 seeds 113 and 119: BUY_GEMS at
    # the gate, RESURRECT_DEAD inside, ~28,000 steps until the party wiped).
    at_exotic_island = cur_map_id == 12 or (
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
        and not saving_to_resurrect(party)
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
        if (
            any(m.status == Status.POISONED for m in living)
            and party.gold >= 100
            and not alcort_coming(party, cur_map_id)
        ):
            return Goal.CURE_POISON
        return Goal.GRIND_AND_LEVEL

    if (
        cur_map_id not in (13, 15, 16, 17, 18, 19, 20)
        and not (at_exotic_island and not living_has_exotics and party.food >= 100)
        and any(m.status == Status.POISONED for m in living)
        and party.gold >= 100
        and not alcort_coming(party, cur_map_id)
    ):
        return Goal.CURE_POISON

    has_all_cards = all(any(m.cards[i] > 0 for m in living) for i in range(4))
    has_remaining_marks = all(any(m.marks[i] > 0 for m in living) for i in (1, 2, 3))

    # Live run 2026-11-22: a return trip sailed in with no keys budgeted;
    # the intelligence shrine (6,6) lies behind the locked door (10,6) and
    # the exit whirlpool's basin behind the water door (39,61), so with the
    # last key spent the party was stranded on Ambrosia. Keep one key for
    # the way out: down to it, leave.
    if cur_map_id == 13:
        has_key = any(m.keys > 0 for m in living)
        needs_key_card = any(not any(m.cards[idx] > 0 for m in living) for idx in (0, 2))
        if (
            max(m.level for m in living) < 5
            or not all(m.marks[0] > 0 for m in party.members)
            or any(m.food < AMBROSIA_ABORT_FOOD for m in living)
            or (not has_all_cards and needs_key_card and not has_key)
            or (has_all_cards and not needs_shrine_stats(party))
            or sum(m.keys for m in living) <= AMBROSIA_EXIT_KEYS
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

    # One laggard may trail: past level 5 needs the Mark of Kings, so the
    # rest can't gain anything more until it is fetched, and the laggard
    # (usually the Cleric, whose kills are rare) levels in the dungeon.
    # Batch 3bb71ce b1: waiting for all four, 9 of 10 seeds starved at
    # levels 5/5/2/5.
    if sorted(m.level for m in living)[min(1, len(living) - 1)] < 5:
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
            # A member with no food turns a dungeon round at the door (it
            # leaves the moment anyone's food is 0), so too broke to buy
            # food it grinds for the gold instead of walking in and out
            # (batch cab7a2a seeds 170, 172: ~75,000 steps each at dungeon
            # 17's door).
            if any(m.food <= 0 for m in living):
                return Goal.GRIND_AND_LEVEL
        return Goal.GET_REMAINING_MARKS

    if not has_all_cards:
        if cur_map_id == 13:
            return Goal.AMBROSIA_CARDS_SHRINES
        if sum(m.keys for m in living) < 4 and party.gold >= 50:
            return Goal.BUY_KEYS
        needed_keys = sum(
            1 for idx in (0, 2) if not any(m.cards[idx] > 0 for m in living)
        )
        if len(living) < len(party.members) or party.gold < ambrosia_trip_gold(party, needed_keys):
            return Goal.GRIND_AND_LEVEL
        if sum(m.keys for m in living) < AMBROSIA_CARD_KEYS:
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

    # Return trips for stats (user ruling 2026-11-22): with the gold for the
    # rest of the plan (one trip's worth at most), sail back to Ambrosia.
    trip_gold = return_trip_gold(party)
    if (
        cur_map_id != 2  # Castle Exodus: once inside, see it through
        and trip_gold
        and len(living) == len(party.members)
        and party.gold >= trip_gold
    ):
        if sum(m.keys for m in living) < AMBROSIA_RETURN_KEYS:
            return Goal.BUY_KEYS
        if any(m.food < AMBROSIA_ENTRY_FOOD for m in living):
            return Goal.BUY_FOOD
        return Goal.SAIL_WHIRLPOOL

    if cur_map_id != 2 and min(m.level for m in living) < 25:
        return Goal.GRIND_AND_LEVEL

    # No castle until the stat plan's return trips are bought (user ruling
    # 2026-11-22): under LairWare damage a level-25 party with STR 39 and
    # 70/75 caster MP lost a member in Castle Exodus. Grinding here raids
    # Death Gulch for the gold, and the return-trip goal above sails.
    if cur_map_id != 2 and return_trip_cost(party) > 0:
        # The gold comes from Death Gulch, and the raid needs 4 keys for its
        # doors (user live trace 2026-11-22, trace_20261122-151023: all
        # cards and marks, level 25+, 3 keys: no raid after step 53,837, and
        # 5,549 gold went on food until the party was broke).
        keys_short = DEATH_GULCH_KEYS - sum(m.keys for m in living)
        # Buy them only while the bribe gold survives the purchase.
        if keys_short > 0 and party.gold >= DEATH_GULCH_BRIBE_GOLD + 50 * keys_short:
            return Goal.BUY_KEYS
        return Goal.GRIND_AND_LEVEL

    return Goal.CONQUER_EXODUS
