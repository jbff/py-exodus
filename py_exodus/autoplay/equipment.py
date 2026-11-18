"""Equipment ranking, chest-loot handoff, and shop-upgrade planning for Full Autoplay."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from py_exodus.constants import ArmorType, Profession, WeaponType

if TYPE_CHECKING:
    from py_exodus.entities.character import Character
    from py_exodus.entities.party import Party

# Profession-allowed weapon sets (matching data/weapons.json)
_CLERIC_WEAPONS: frozenset[WeaponType] = frozenset({WeaponType.DAGGER, WeaponType.MACE, WeaponType.EXOTIC})
_WIZARD_WEAPONS: frozenset[WeaponType] = frozenset({WeaponType.DAGGER, WeaponType.EXOTIC})
_THIEF_WEAPONS: frozenset[WeaponType] = frozenset(
    {
        WeaponType.DAGGER,
        WeaponType.MACE,
        WeaponType.SLING,
        WeaponType.AXE,
        WeaponType.BOW,
        WeaponType.SWORD,
        WeaponType.EXOTIC,
    }
)
_FIGHTER_WEAPONS: frozenset[WeaponType] = frozenset(wt for wt in WeaponType if wt != WeaponType.NONE)
_RANGER_WEAPONS: frozenset[WeaponType] = _FIGHTER_WEAPONS - frozenset(
    {WeaponType.GLOVES, WeaponType.AXE_P4, WeaponType.BOW_P4, WeaponType.SWORD_P4}
)

PROFESSION_WEAPONS: dict[Profession, frozenset[WeaponType]] = {
    Profession.FIGHTER: _FIGHTER_WEAPONS,
    Profession.PALADIN: _FIGHTER_WEAPONS,
    Profession.BARBARIAN: _FIGHTER_WEAPONS,
    Profession.LARK: _FIGHTER_WEAPONS,
    Profession.RANGER: _RANGER_WEAPONS,
    Profession.THIEF: _THIEF_WEAPONS,
    Profession.CLERIC: _CLERIC_WEAPONS,
    Profession.DRUID: _CLERIC_WEAPONS,
    Profession.ILLUSIONIST: _CLERIC_WEAPONS,
    Profession.WIZARD: _WIZARD_WEAPONS,
    Profession.ALCHEMIST: _WIZARD_WEAPONS,
}

# Profession-allowed armor sets (matching data/armors.json)
_WIZARD_ARMORS: frozenset[ArmorType] = frozenset({ArmorType.CLOTH, ArmorType.EXOTIC})
_THIEF_ARMORS: frozenset[ArmorType] = frozenset({ArmorType.CLOTH, ArmorType.LEATHER, ArmorType.EXOTIC})
_CLERIC_ARMORS: frozenset[ArmorType] = frozenset(
    {ArmorType.CLOTH, ArmorType.LEATHER, ArmorType.CHAIN, ArmorType.EXOTIC}
)
_PALADIN_ARMORS: frozenset[ArmorType] = frozenset(
    {ArmorType.CLOTH, ArmorType.LEATHER, ArmorType.CHAIN, ArmorType.PLATE, ArmorType.EXOTIC}
)
_FIGHTER_ARMORS: frozenset[ArmorType] = frozenset(at for at in ArmorType if at != ArmorType.NONE)

PROFESSION_ARMORS: dict[Profession, frozenset[ArmorType]] = {
    Profession.FIGHTER: _FIGHTER_ARMORS,
    Profession.RANGER: _FIGHTER_ARMORS,
    Profession.PALADIN: _PALADIN_ARMORS,
    Profession.CLERIC: _CLERIC_ARMORS,
    Profession.THIEF: _THIEF_ARMORS,
    Profession.BARBARIAN: _THIEF_ARMORS,
    Profession.ILLUSIONIST: _THIEF_ARMORS,
    Profession.WIZARD: _WIZARD_ARMORS,
    Profession.ALCHEMIST: _WIZARD_ARMORS,
    Profession.DRUID: _WIZARD_ARMORS,
    Profession.LARK: _WIZARD_ARMORS,
}

# Power ranking (higher is strictly better)
WEAPON_RANK: dict[WeaponType, int] = {
    WeaponType.NONE: 0,
    WeaponType.DAGGER: 1,
    WeaponType.MACE: 2,
    WeaponType.AXE: 3,
    WeaponType.SWORD: 4,
    WeaponType.SWORD_2H: 5,
    WeaponType.SLING: 6,
    WeaponType.BOW: 7,
    WeaponType.AXE_P2: 8,
    WeaponType.SWORD_P2: 9,
    WeaponType.BOW_P2: 10,
    WeaponType.GLOVES: 11,
    WeaponType.AXE_P4: 12,
    WeaponType.SWORD_P4: 13,
    WeaponType.BOW_P4: 14,
    WeaponType.EXOTIC: 15,
}

ARMOR_RANK: dict[ArmorType, int] = {
    ArmorType.NONE: 0,
    ArmorType.CLOTH: 1,
    ArmorType.LEATHER: 2,
    ArmorType.CHAIN: 3,
    ArmorType.PLATE: 4,
    ArmorType.CHAIN_P2: 5,
    ArmorType.PLATE_P2: 6,
    ArmorType.EXOTIC: 7,
}


@dataclass(frozen=True)
class ShopUpgrade:
    """Represents a concrete shop purchase for a specific party member."""

    member_idx: int  # 1-based
    kind: str  # "weapon" or "armor"
    item_letter: str
    price: int
    dawn_only: bool
    rank_gain: int


# Shop upgrade ladders: (type, vendor_letter, price, dawn_only)
_WEAPON_LADDER: tuple[tuple[WeaponType, str, int, bool], ...] = (
    (WeaponType.DAGGER, "b", 5, False),
    (WeaponType.MACE, "c", 30, False),
    (WeaponType.SLING, "d", 60, False),
    (WeaponType.SWORD, "g", 200, False),
    (WeaponType.SWORD_2H, "h", 250, False),
    (WeaponType.BOW, "f", 350, False),
    (WeaponType.AXE_P2, "i", 400, True),
    (WeaponType.SWORD_P2, "k", 800, True),
    (WeaponType.BOW_P2, "j", 1050, True),
    (WeaponType.AXE_P4, "m", 2700, True),
    (WeaponType.SWORD_P4, "o", 4550, True),
    (WeaponType.BOW_P4, "n", 6550, True),
)

_ARMOR_LADDER: tuple[tuple[ArmorType, str, int, bool], ...] = (
    (ArmorType.CLOTH, "b", 75, False),
    (ArmorType.LEATHER, "c", 195, False),
    (ArmorType.CHAIN, "d", 575, False),
    (ArmorType.PLATE, "e", 2500, False),
    (ArmorType.CHAIN_P2, "f", 6130, True),
    (ArmorType.PLATE_P2, "g", 8250, True),
)


def can_use_weapon(member: Character, wt: WeaponType) -> bool:
    """Return True if ``member``'s profession can ready ``wt``."""
    return wt in PROFESSION_WEAPONS.get(member.profession, _FIGHTER_WEAPONS)


def can_use_armor(member: Character, at: ArmorType) -> bool:
    """Return True if ``member``'s profession can wear ``at``."""
    return at in PROFESSION_ARMORS.get(member.profession, _FIGHTER_ARMORS)


_RANGED_BOWS: frozenset[WeaponType] = frozenset(
    {WeaponType.BOW, WeaponType.BOW_P2, WeaponType.BOW_P4}
)


def _weapon_score(wt: WeaponType, prefer_ranged: bool) -> int:
    rank = WEAPON_RANK.get(wt, 0)
    if prefer_ranged and wt in _RANGED_BOWS:
        return rank + 10
    return rank


def best_owned_weapon(member: Character, prefer_ranged: bool = True) -> WeaponType | None:
    """Return the best usable weapon in ``member.weapons`` strictly better than equipped."""
    cur_rank = _weapon_score(member.weapon, prefer_ranged)
    best: WeaponType | None = None
    best_rank = cur_rank
    for wt, cnt in member.weapons.items():
        if cnt <= 0 or wt == WeaponType.NONE or not can_use_weapon(member, wt):
            continue
        r = _weapon_score(wt, prefer_ranged)
        if r > best_rank:
            best = wt
            best_rank = r
    return best


def best_owned_armor(member: Character) -> ArmorType | None:
    """Return the best usable armor in ``member.armors`` strictly better than equipped."""
    cur_rank = ARMOR_RANK.get(member.armor, 0)
    best: ArmorType | None = None
    best_rank = cur_rank
    for at, cnt in member.armors.items():
        if cnt <= 0 or at == ArmorType.NONE or not can_use_armor(member, at):
            continue
        r = ARMOR_RANK.get(at, 0)
        if r > best_rank:
            best = at
            best_rank = r
    return best


def best_hand_transfer(party: Party) -> tuple[int, int] | None:
    """Find a useful ``H`` (Hand Equipment) transfer from one member to another.

    Mirrors ``_prompt_hand_equipment`` selection order: first unequipped weapon
    with ``cnt > 0 and w != m1.weapon``, else first unequipped armor with
    ``cnt > 0 and a != m1.armor``. Only proposes a transfer when the receiving
    member can use the item and it strictly upgrades their current gear (and the
    sender does not themselves prefer to equip it).
    """
    for i, m1 in enumerate(party.members):
        if m1.is_dead():
            continue
        # If m1 wants to equip something they already hold, let R/W run first.
        if best_owned_weapon(m1) is not None or best_owned_armor(m1) is not None:
            continue

        picked_w: WeaponType | None = None
        for w, cnt in m1.weapons.items():
            if cnt > 0 and w != m1.weapon:
                picked_w = w
                break

        if picked_w is not None:
            w_rank = WEAPON_RANK.get(picked_w, 0)
            for j, m2 in enumerate(party.members):
                if j == i or m2.is_dead():
                    continue
                if can_use_weapon(m2, picked_w) and w_rank > WEAPON_RANK.get(m2.weapon, 0):
                    return (i + 1, j + 1)
            continue

        picked_a: ArmorType | None = None
        for a, cnt in m1.armors.items():
            if cnt > 0 and a != m1.armor:
                picked_a = a
                break

        if picked_a is not None:
            a_rank = ARMOR_RANK.get(picked_a, 0)
            for j, m2 in enumerate(party.members):
                if j == i or m2.is_dead():
                    continue
                if can_use_armor(m2, picked_a) and a_rank > ARMOR_RANK.get(m2.armor, 0):
                    return (i + 1, j + 1)

    return None


def best_shop_upgrade(party: Party, *, include_wizard_dagger: bool = False) -> ShopUpgrade | None:
    """Return the best affordable shop upgrade for any living party member.

    Starter phase: if any living member is still missing starter gear
    (non-Wizard with ``WeaponType.NONE``, or ``ArmorType.NONE``), restrict to
    non-Dawn shops so the party outfits at the nearest town first without
    pooling all gold into one expensive Dawn item.

    Upgrade phase: once everyone has starter gear, pools living members' gold
    and targets the highest-tier affordable upgrade (including Dawn's +2/+4
    magic weapons and armor).
    """
    living = [(i + 1, m) for i, m in enumerate(party.members) if not m.is_dead()]
    if not living:
        return None
    total_gold = sum(m.gold for _, m in living)

    needs_starter = any(
        (m.weapon == WeaponType.NONE and m.profession not in (Profession.WIZARD, Profession.ALCHEMIST) and total_gold >= 5)
        or (m.armor == ArmorType.NONE and total_gold >= 75)
        for _, m in living
    )

    # At level 3+ (when Giants/stronger monsters spawn), keep a 500g resurrection reserve
    spendable_gold = (
        max(0, total_gold - 500)
        if (not needs_starter and max(m.level for _, m in living) >= 3)
        else total_gold
    )

    candidates: list[ShopUpgrade] = []
    for idx, m in living:
        cur_w_rank = WEAPON_RANK.get(m.weapon, 0)
        best_w: ShopUpgrade | None = None
        for wt, letter, price, dawn_only in _WEAPON_LADDER:
            if not can_use_weapon(m, wt):
                continue
            if needs_starter and (dawn_only or price > 150):
                continue
            if wt == WeaponType.DAGGER and m.profession in (Profession.WIZARD, Profession.ALCHEMIST) and not include_wizard_dagger:
                continue
            r = WEAPON_RANK.get(wt, 0)
            if r > cur_w_rank and spendable_gold >= price:
                if any(cnt > 0 and WEAPON_RANK.get(ow, 0) >= r for ow, cnt in m.weapons.items()):
                    continue
                best_w = ShopUpgrade(
                    member_idx=idx,
                    kind="weapon",
                    item_letter=letter,
                    price=price,
                    dawn_only=dawn_only,
                    rank_gain=r - cur_w_rank,
                )
        if best_w is not None and (not needs_starter or m.weapon == WeaponType.NONE):
            candidates.append(best_w)

        cur_a_rank = ARMOR_RANK.get(m.armor, 0)
        best_a: ShopUpgrade | None = None
        for at, letter, price, dawn_only in _ARMOR_LADDER:
            if not can_use_armor(m, at):
                continue
            if needs_starter and (dawn_only or price > 150):
                continue
            r = ARMOR_RANK.get(at, 0)
            if r > cur_a_rank and spendable_gold >= price:
                if any(cnt > 0 and ARMOR_RANK.get(oa, 0) >= r for oa, cnt in m.armors.items()):
                    continue
                best_a = ShopUpgrade(
                    member_idx=idx,
                    kind="armor",
                    item_letter=letter,
                    price=price,
                    dawn_only=dawn_only,
                    rank_gain=r - cur_a_rank,
                )
        if best_a is not None and (not needs_starter or m.armor == ArmorType.NONE):
            candidates.append(best_a)

    if not candidates:
        return None

    def _priority(up: ShopUpgrade) -> tuple[int, int, int, int]:
        m = party.members[up.member_idx - 1]
        is_empty = (
            (up.kind == "weapon" and m.weapon == WeaponType.NONE)
            or (up.kind == "armor" and m.armor == ArmorType.NONE)
        )
        can_self_pay = 1 if m.gold >= up.price else 0
        # Armor tiers are coarser (8 ranks vs 16 weapon ranks); weight Chain/Plate+
        # upgrades so fighters/paladins actually upgrade Leather -> Chain/Plate.
        effective_gain = up.rank_gain * 4 if (up.kind == "armor" and up.price >= 500) else up.rank_gain
        return (1 if is_empty else 0, can_self_pay if needs_starter else 0, effective_gain, -up.price)

    return max(candidates, key=_priority)
