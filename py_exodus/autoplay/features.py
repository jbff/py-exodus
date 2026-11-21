"""Shared macro feature extractor for Phase 0 EV planning and Phase 3 neural critic."""
from __future__ import annotations

from typing import TYPE_CHECKING

from py_exodus.autoplay.equipment import best_shop_upgrade
from py_exodus.autoplay.planner import (
    _normalize_map_id,
    member_needs_shrine_stat,
    needs_food,
    needs_shrine_stats,
)
from py_exodus.constants import ArmorType, Direction, Profession, Status, Transport, WeaponType

if TYPE_CHECKING:
    from py_exodus.entities.party import Party

MACRO_FEATURE_NAMES: tuple[str, ...] = (
    # Party vitals
    "min_hp_ratio",
    "mean_hp_ratio",
    "dead_count",
    "ash_count",
    "poisoned_count",
    "min_mp",
    "can_alcort",
    "can_sequi",
    # Sustenance & economy
    "total_food",
    "min_member_food",
    "zero_food_count",
    "food_runway_turns",
    "party_gold",
    "total_keys",
    "total_gems",
    "total_torches",
    # Progression
    "min_level",
    "marks_mask",
    "cards_mask",
    "exotics_weapons_ratio",
    "exotics_armor_ratio",
    "any_below_shrine_cap",
    "exodus_done",
    "living_count",
    "member_count",
    "has_shop_upgrade",
    # Navigation & hazard context
    "cur_map_id",
    "on_ship",
    "ship_hull",
    "wind_dir_idx",
    "trammel_phase",
    "felucca_phase",
    "dawn_open",
    "nearest_pirate_dist",
    "at_exotic_island",
)

_WIND_TO_IDX: dict[Direction | None, float] = {
    None: -1.0,
    Direction.NORTH: 0.0,
    Direction.EAST: 1.0,
    Direction.SOUTH: 2.0,
    Direction.WEST: 3.0,
}

_SHRINE_STAT_CAPS: tuple[tuple[str, str], ...] = (
    ("strength", "max_str"),
    ("dexterity", "max_dex"),
    ("wisdom", "max_wis"),
    ("intelligence", "max_int"),
)


def extract_macro_features(
    party: Party,
    map_id: int | str | None = None,
    screen=None,
) -> dict[str, float]:
    """Extract normalized numeric macro features from live Party and optional Screen state."""
    cur_map_id = float(_normalize_map_id(party, map_id))
    members = list(getattr(party, "members", ()))
    living = [m for m in members if not m.is_dead()]

    if living:
        hp_ratios = [m.hp / max(1, m.max_hp) for m in living]
        min_hp_ratio = min(hp_ratios)
        mean_hp_ratio = sum(hp_ratios) / len(living)
        min_mp = float(min(m.mp for m in living))
        min_member_food = float(min(m.food for m in living))
        zero_food_count = float(sum(1 for m in living if m.food <= 0))
        min_level = float(min(m.level for m in living))
        total_keys = float(sum(m.keys for m in living))
        total_gems = float(sum(m.gems for m in living))
        total_torches = float(sum(m.torches for m in living))
    else:
        min_hp_ratio = 0.0
        mean_hp_ratio = 0.0
        min_mp = 0.0
        min_member_food = 0.0
        zero_food_count = 0.0
        min_level = 0.0
        total_keys = 0.0
        total_gems = 0.0
        total_torches = 0.0

    dead_count = float(sum(1 for m in members if m.status == Status.DEAD))
    ash_count = float(sum(1 for m in members if m.status == Status.ASH))
    poisoned_count = float(sum(1 for m in living if m.status == Status.POISONED))
    can_alcort = float(
        any(
            m.profession in (Profession.CLERIC, Profession.DRUID) and m.mp >= 35
            for m in living
        )
    )
    can_sequi = float(
        any(
            m.profession in (Profession.CLERIC, Profession.DRUID) and m.mp >= 65
            for m in living
        )
    )

    # Living rations only: dead members never eat, and a zeroed dead pouch
    # must not read as an empty larder (see planner.needs_food).
    total_food = float(sum(m.food for m in living)) if living else 0.0
    food_runway_turns = min_member_food * 10.0 if living else 0.0
    party_gold = float(getattr(party, "gold", 0))

    marks_mask = 0
    for i in range(4):
        if any(m.marks[i] > 0 for m in living):
            marks_mask |= 1 << i
    cards_mask = 0
    for i in range(4):
        if any(m.cards[i] > 0 for m in living):
            cards_mask |= 1 << i

    denom = max(1, len(members))
    exotics_weapons_ratio = (
        sum(
            1
            for m in members
            if m.weapon == WeaponType.EXOTIC or m.weapons.get(WeaponType.EXOTIC, 0) > 0
        )
        / denom
    )
    exotics_armor_ratio = (
        sum(
            1
            for m in members
            if m.armor == ArmorType.EXOTIC or m.armors.get(ArmorType.EXOTIC, 0) > 0
        )
        / denom
    )
    any_below_shrine_cap = float(
        any(
            member_needs_shrine_stat(m, stat_attr, cap_attr)
            for m in living
            for stat_attr, cap_attr in _SHRINE_STAT_CAPS
        )
    )
    exodus_done = float(
        getattr(party, "exodus_defeated", 0) > 0
        or getattr(party, "exodus_cards_status", 0) == 0xF
    )
    has_shop_upgrade = float(
        len(members) >= 4
        and bool(living)
        and best_shop_upgrade(party, include_wizard_dagger=True) is not None
    )

    on_ship = float(getattr(party, "transport", Transport.FOOT) == Transport.SHIP)
    ship_hull = float(
        getattr(screen, "ship_hull", getattr(party, "ship_hull", 50))
        if screen is not None
        else getattr(party, "ship_hull", 50)
    )
    wind_dir_idx = _WIND_TO_IDX.get(getattr(party, "wind_direction", None), -1.0)
    trammel_phase = float(getattr(screen, "trammel_phase", 0) if screen is not None else 0)
    felucca_phase = float(getattr(screen, "felucca_phase", 0) if screen is not None else 0)
    dawn_open = float(trammel_phase == 0.0 and felucca_phase == 0.0)

    px = getattr(party, "x", 0)
    py = getattr(party, "y", 0)
    gmap = getattr(screen, "game_map", None) if screen is not None else None
    pirate_dists = [
        (
            min((c["x"] - px) % gmap.width, (px - c["x"]) % gmap.width)
            + min((c["y"] - py) % gmap.height, (py - c["y"]) % gmap.height)
            if gmap is not None and getattr(gmap, "width", 0) > 0 and getattr(gmap, "height", 0) > 0
            else abs(c["x"] - px) + abs(c["y"] - py)
        )
        for c in (getattr(screen, "creatures", ()) if screen is not None else ())
        if str(c.get("tile_name") or c.get("tile") or "").lower() == "pirate"
        and "x" in c
        and "y" in c
    ]
    nearest_pirate_dist = float(min(pirate_dists)) if pirate_dists else 99.0

    at_exotic_island = float(
        int(cur_map_id) == 0
        and getattr(party, "transport", Transport.FOOT) == Transport.FOOT
        and any(abs(px - tx) + abs(py - ty) <= 4 for tx, ty in ((33, 3), (19, 44)))
    )

    return {
        "min_hp_ratio": float(min_hp_ratio),
        "mean_hp_ratio": float(mean_hp_ratio),
        "dead_count": dead_count,
        "ash_count": ash_count,
        "poisoned_count": poisoned_count,
        "min_mp": min_mp,
        "can_alcort": can_alcort,
        "can_sequi": can_sequi,
        "total_food": total_food,
        "min_member_food": min_member_food,
        "zero_food_count": zero_food_count,
        "food_runway_turns": food_runway_turns,
        "party_gold": party_gold,
        "total_keys": total_keys,
        "total_gems": total_gems,
        "total_torches": total_torches,
        "min_level": min_level,
        "marks_mask": float(marks_mask),
        "cards_mask": float(cards_mask),
        "exotics_weapons_ratio": float(exotics_weapons_ratio),
        "exotics_armor_ratio": float(exotics_armor_ratio),
        "any_below_shrine_cap": any_below_shrine_cap,
        "exodus_done": exodus_done,
        "living_count": float(len(living)),
        "member_count": float(len(members)),
        "has_shop_upgrade": has_shop_upgrade,
        "cur_map_id": cur_map_id,
        "on_ship": on_ship,
        "ship_hull": ship_hull,
        "wind_dir_idx": wind_dir_idx,
        "trammel_phase": trammel_phase,
        "felucca_phase": felucca_phase,
        "dawn_open": dawn_open,
        "nearest_pirate_dist": nearest_pirate_dist,
        "at_exotic_island": at_exotic_island,
    }


def macro_feature_vector(features: dict[str, float]) -> list[float]:
    """Return ordered float vector matching MACRO_FEATURE_NAMES."""
    return [float(features[name]) for name in MACRO_FEATURE_NAMES]
