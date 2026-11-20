"""Outcome-filtered CombatArena rollout collector for Phase 1 behavioral cloning."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import random
import subprocess
from typing import Any

from py_exodus.assets import AssetManager
from py_exodus.combat.arena import CombatArena
from py_exodus.combat.auto_combat import choose_auto_combat_action
from py_exodus.constants import ArmorType, Profession, Race, Transport, WeaponType
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.nn.combat_env import (
    action_to_index,
    encode_combat_state,
    legal_action_mask,
)

TRAIN_SEED_MAX = 899
HOLDOUT_SEED_MIN = 900
HOLDOUT_SEED_MAX = 999

_DEFAULT_CONFLICT_MAP_IDS = (34, 35, 36, 37, 38)
_DEFAULT_CREATURES = ("orc", "skeleton", "goblin", "troll", "thief", "mage", "giant")

# Full battlefield space (2026-11-20): every spawnable battle creature
# from creatures.xml (encounterSize >= 1) crossed with every conflict map
# that pairing actually reaches at game time, per
# screens/overworld.get_combat_map_id:
#   land creature + FOOT -> tile-dependent {34, 35, 36, 37, 38}
#   swims    + FOOT      -> 38 (CONFLICT_SHORE)
#   sails    + FOOT      -> 33 (CONFLICT_SHIP_TOP)
#   land     + SHIP      -> 40 (CONFLICT_SHIP_BOTTOM)
#   swims    + SHIP      -> 39 (CONFLICT_SHIP)
#   sails    + SHIP      -> 41 (CONFLICT_BOTH_SHIPS)
_BATTLE_CREATURE_FAMILIES: dict[str, tuple[bool, bool]] = {
    # tile: (swims, sails)
    "orc": (False, False),
    "skeleton": (False, False),
    "thief": (False, False),
    "giant": (False, False),
    "daemon": (False, False),
    "fighter": (False, False),
    "wizard": (False, False),
    "pincher": (False, False),
    "dragon": (False, False),
    "balron": (False, False),
    "pirate": (False, True),
    "serpent": (True, False),
    "squid": (True, False),
}


def _conflict_maps_for(creature_tile: str, transports: "Transport") -> tuple[int, ...]:
    """Reachable conflict maps for (creature, party transport), game-true."""
    swims, sails = _BATTLE_CREATURE_FAMILIES.get(creature_tile, (False, False))
    if transports == Transport.SHIP:
        if sails:
            return (41,)  # CONFLICT_BOTH_SHIPS
        if swims:
            return (39,)  # CONFLICT_SHIP
        return (40,)  # CONFLICT_SHIP_BOTTOM
    if swims:
        return (38,)  # CONFLICT_SHORE
    if sails:
        return (33,)  # CONFLICT_SHIP_TOP
    return (34, 35, 36, 37, 38)


def battle_terrain_cells(
    *,
    monster_counts: range | tuple[int, ...] = range(1, 9),
) -> tuple[tuple[str, "Transport", int, int], ...]:
    """Enumerate every reachable (creature, transport, map, monster_count) cell.

    The engine picks the conflict map from the encounter context
    (``get_combat_map_id``); the dataset must match that space exactly, not
    a hand-picked subset — the original full-trainer gap was ship maps
    (39/40/41) and sea/boarding creatures, which the combat BC/PPO nets had
    never seen (2026-11-20 ship-vs-serpent loop diagnosis).
    """
    cells: list[tuple[str, "Transport", int, int]] = []
    for tile in sorted(_BATTLE_CREATURE_FAMILIES):
        for transport in (Transport.FOOT, Transport.SHIP):
            for cmap_id in _conflict_maps_for(tile, transport):
                for count in monster_counts:
                    cells.append((tile, transport, cmap_id, count))
    return tuple(cells)


@dataclass
class CombatSample:
    """Single encoded (state, mask, expert_action) combat transition."""

    grid: list[list[list[float]]]
    context: list[float]
    mask: list[bool]
    action_idx: int


def current_git_sha() -> str:
    """Return current HEAD commit SHA or 'unknown' outside a git worktree."""
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
            .decode("utf-8")
            .strip()
        )
    except Exception:
        return "unknown"


def validate_train_seeds(seeds: list[int] | tuple[int, ...]) -> None:
    """Enforce Seed Hygiene: training seeds must stay strictly in [0, 899]."""
    for s in seeds:
        if not (0 <= s <= TRAIN_SEED_MAX):
            raise ValueError(
                f"Seed {s} violates Seed Hygiene: training seeds must be in [0, {TRAIN_SEED_MAX}] "
                f"(holdout {HOLDOUT_SEED_MIN}-{HOLDOUT_SEED_MAX} is never trained on)."
            )


def _make_sample_party(level: int, rng: random.Random) -> Party:
    p = Party()
    specs = (
        ("SHADOW", "M", Race.ELF, Profession.THIEF, 15, 25, 10, 10),
        ("GRUMM", "M", Race.DWARF, Profession.FIGHTER, 25, 15, 10, 10),
        ("SERENA", "F", Race.BOBIT, Profession.CLERIC, 15, 15, 10, 25),
        ("ZIRCON", "M", Race.FUZZY, Profession.WIZARD, 15, 15, 25, 10),
    )
    for name, sex, race, prof, s, d, i, w in specs:
        m = Character(name, sex, race, prof, strength=s, dexterity=d, intelligence=i, wisdom=w, gold=200, food=300)
        m.level = level
        m.hp = m.max_hp = level * 100
        m.mp = m.max_mp = max(25, w * 2) if prof == Profession.CLERIC else (max(25, i * 2) if prof == Profession.WIZARD else 0)
        m.weapon = rng.choice((WeaponType.SWORD, WeaponType.BOW, WeaponType.MACE, WeaponType.EXOTIC))
        m.armor = rng.choice((ArmorType.LEATHER, ArmorType.CHAIN, ArmorType.PLATE, ArmorType.EXOTIC))
        p.add_member(m)
    return p


def run_combat_episode(
    am: AssetManager,
    seed: int,
    *,
    level: int = 6,
    max_turns: int = 60,
) -> tuple[bool, int, list[CombatSample]]:
    """Run one CombatArena episode using auto_combat and return (won, ally_deaths, samples)."""
    rng = random.Random(seed)
    random.seed(seed)
    party = _make_sample_party(level=level, rng=rng)
    from py_exodus.world.loader import load_map

    cmap_id = rng.choice(_DEFAULT_CONFLICT_MAP_IDS)
    cmap = load_map(cmap_id, am)

    creature_tile = rng.choice(_DEFAULT_CREATURES)
    monster_count = rng.randint(1, 5)
    arena = CombatArena(party, cmap, asset_mgr=am, creature_tile=creature_tile, monster_count=monster_count)
    screen_stub = type(
        "_Scr",
        (),
        {
            "trammel_phase": rng.randrange(24),
            "felucca_phase": rng.randrange(8),
            "creatures": (),
        },
    )()

    samples: list[CombatSample] = []
    steps = 0
    while not arena.is_finished and steps < max_turns * 4:
        m_idx = arena.active_party_member_idx
        action = choose_auto_combat_action(arena, m_idx, asset_mgr=am)
        grid, ctx = encode_combat_state(arena, m_idx, screen=screen_stub, asset_mgr=am)
        mask = legal_action_mask(arena, m_idx, asset_mgr=am)
        a_idx = action_to_index(action)
        if not mask[a_idx]:
            a_idx = 14
        samples.append(CombatSample(grid=grid, context=ctx, mask=mask, action_idx=a_idx))
        arena.execute_turn(action)
        steps += 1

    ally_deaths = sum(1 for m in party.members if m.is_dead())
    won = bool(arena.is_finished and arena.is_victory)
    return won, ally_deaths, samples


def _make_diverse_party(level: int, rng: random.Random) -> Party:
    """Sample a party across ALL realistic capability cases (v3 dataset).

    The fixed prototype party made the net blind to most of the real game:
    casters always ran the same MP pool (spell count drives strategy — e.g.
    Castle Fire's high-level spells need 50+ MP), gear was uniform instead
    of level-shaped, and nobody was ever wounded. This rolls:
      - casters' wis/int from weak (10) to font/shrine-boosted (75),
        weighted higher with level; MP = wis/int directly (engine truth)
      - fighter/thief stat rolls on the same ladder (15..99)
      - level-shaped weapon/armor pools (Dagger/Sling early, Exotic/P4 late)
      - wounded members (0.35-1.0 HP fraction) in most fights
      - gold/food in realistic ranges
    """
    weapon_pool: tuple[WeaponType, ...]
    armor_pool: tuple[ArmorType, ...]
    if level <= 3:
        weapon_pool = (WeaponType.DAGGER, WeaponType.MACE, WeaponType.SLING)
        armor_pool = (ArmorType.CLOTH, ArmorType.LEATHER)
    elif level <= 9:
        weapon_pool = (WeaponType.SWORD, WeaponType.BOW, WeaponType.AXE, WeaponType.MACE)
        armor_pool = (ArmorType.LEATHER, ArmorType.CHAIN)
    elif level <= 15:
        weapon_pool = (
            WeaponType.SWORD, WeaponType.BOW, WeaponType.AXE,
            WeaponType.SWORD_P2, WeaponType.BOW_P2,
        )
        armor_pool = (ArmorType.CHAIN, ArmorType.PLATE)
    else:
        weapon_pool = (
            WeaponType.EXOTIC, WeaponType.BOW_P4, WeaponType.SWORD_P4,
            WeaponType.AXE_P4,
        )
        armor_pool = (ArmorType.PLATE, ArmorType.EXOTIC)

    def _caster_stat(low_level: bool) -> int:
        if low_level:
            return rng.choice((10, 15, 20, 25))
        return rng.choices((25, 35, 50, 75), weights=(3, 2, 3, 2))[0]

    def _warrior_stat(low_level: bool) -> int:
        if low_level:
            return rng.choice((15, 25))
        return rng.choices((25, 50, 99), weights=(1, 1, 2))[0]

    def _noncore_stat() -> int:
        return rng.choice((10, 15))

    low_level = level <= 9

    def _make(name: str, sex: str, race: Race, prof: Profession, hp_fraction: float) -> Character:
        char = Character(
            name=name,
            sex=sex,
            race=race,
            profession=prof,
            strength=_warrior_stat(low_level) if prof == Profession.FIGHTER else _noncore_stat(),
            dexterity=_warrior_stat(low_level) if prof == Profession.THIEF else _noncore_stat(),
            intelligence=_caster_stat(low_level) if prof == Profession.WIZARD else _noncore_stat(),
            wisdom=_caster_stat(low_level) if prof == Profession.CLERIC else _noncore_stat(),
            gold=rng.randint(100, 4500),
            food=rng.randint(100, 900),
        )
        char.level = level
        char.max_hp = level * 100
        char.hp = max(1, int(char.max_hp * hp_fraction))
        mp = char.compute_max_mp()
        char.max_mp = mp
        char.mp = mp
        return char

    specs = (
        ("SHADOW", "M", Race.ELF, Profession.THIEF),
        ("GRUMM", "M", Race.DWARF, Profession.FIGHTER),
        ("SERENA", "F", Race.BOBIT, Profession.CLERIC),
        ("ZIRCON", "M", Race.FUZZY, Profession.WIZARD),
    )
    party = Party()
    for name, sex, race, prof in specs:
        # Wounded parties are the norm mid-dungeon; fresh full-HP fights
        # stay common early, rarer late (autoplay rarely enters at <90%).
        if level <= 3:
            frac = rng.choice((1.0, 1.0, rng.uniform(0.7, 1.0)))
        else:
            frac = rng.choice((1.0, rng.uniform(0.35, 1.0), rng.uniform(0.35, 1.0)))
        char = _make(name, sex, race, prof, frac)
        char.weapons[rng.choice(weapon_pool)] = 1
        char.weapon = rng.choice(weapon_pool)
        char.armors[rng.choice(armor_pool)] = 1
        char.armor = rng.choice(armor_pool)
        party.add_member(char)
    return party


def run_battlefield_episode(
    am: AssetManager,
    seed: int,
    *,
    creature_tile: str,
    transport: Transport,
    cmap_id: int,
    level: int,
    monster_count: int,
    max_turns: int = 60,
) -> tuple[bool, int, list[CombatSample]]:
    """One teacher episode for a specific (creature, transport, map, count) cell.

    Same outcome-filtered symbolic teacher as :func:`run_combat_episode`,
    but the encounter space is pinned so the dataset covers the full
    reachable battlefield (ship battles, sea swimmers, boardings, Exodus
    castle terrain family), not just the land maps the phase-1 net saw.
    """
    rng = random.Random(seed)
    random.seed(seed)
    party = _make_diverse_party(level=level, rng=rng)
    party.transport = transport
    random.seed(seed)
    from py_exodus.world.loader import load_map

    cmap = load_map(cmap_id, am)
    arena = CombatArena(
        party, cmap, asset_mgr=am, creature_tile=creature_tile, monster_count=monster_count
    )
    screen_stub = type(
        "_Scr",
        (),
        {
            "trammel_phase": rng.randrange(24),
            "felucca_phase": rng.randrange(8),
            "creatures": (),
        },
    )()

    samples: list[CombatSample] = []
    steps = 0
    while not arena.is_finished and steps < max_turns * 4:
        m_idx = arena.active_party_member_idx
        action = choose_auto_combat_action(arena, m_idx, asset_mgr=am)
        grid, ctx = encode_combat_state(arena, m_idx, screen=screen_stub, asset_mgr=am)
        mask = legal_action_mask(arena, m_idx, asset_mgr=am)
        a_idx = action_to_index(action)
        if not mask[a_idx]:
            a_idx = 14
        samples.append(CombatSample(grid=grid, context=ctx, mask=mask, action_idx=a_idx))
        arena.execute_turn(action)
        steps += 1

    ally_deaths = sum(1 for m in party.members if m.is_dead())
    won = bool(arena.is_finished and arena.is_victory)
    return won, ally_deaths, samples


def collect_battlefield_dataset(
    seeds: list[int] | tuple[int, ...],
    *,
    assets_dir: str = "data",
    levels: tuple[int, ...] = (3, 6, 9, 12, 16, 20, 25),
    episodes_per_cell: int = 20,
    monster_counts: tuple[int, ...] = tuple(range(1, 9)),
    max_turns: int = 90,
) -> tuple[list[CombatSample], dict[str, Any]]:
    """Outcome-filtered teacher dataset across the full battlefield space.

    Every (creature, transport, conflict map, monster_count) cell from
    :func:`battle_terrain_cells` gets ``episodes_per_cell`` teacher
    episodes; only won episodes contribute samples (BC must imitate
    winners). Stats break out ship-battle vs land coverage so regressions
    in either family are visible.
    """
    validate_train_seeds(seeds)
    am = AssetManager(assets_dir)
    am.load_all()
    cells = battle_terrain_cells(monster_counts=monster_counts)

    samples: list[CombatSample] = []
    stats = {
        "cells": 0,
        "episodes_total": 0,
        "episodes_won": 0,
        "samples": 0,
        "ship_cells_won": 0,
        "ship_cells_total": 0,
        "land_cells_won": 0,
        "land_cells_total": 0,
        "teacher_turns": 0,
    }

    ep_i = 0
    for tile, transport, cmap_id, count in cells:
        stats["cells"] += 1
        is_ship = transport == Transport.SHIP
        cell_won = 0
        for k in range(episodes_per_cell):
            seed = seeds[ep_i % len(seeds)] * 1000 + (ep_i // len(seeds))
            ep_i += 1
            level = levels[ep_i % len(levels)]
            won, deaths, ep_samples = run_battlefield_episode(
                am,
                seed,
                creature_tile=tile,
                transport=transport,
                cmap_id=cmap_id,
                level=level,
                monster_count=count,
                max_turns=max_turns,
            )
            stats["episodes_total"] += 1
            stats["teacher_turns"] += len(ep_samples)
            cell_won += 1 if won else 0
            if not won:
                continue
            stats["episodes_won"] += 1
            samples.extend(ep_samples)
        if is_ship:
            stats["ship_cells_won"] += 1 if cell_won > 0 else 0
            stats["ship_cells_total"] += 1
        else:
            stats["land_cells_won"] += 1 if cell_won > 0 else 0
            stats["land_cells_total"] += 1
    stats["samples"] = len(samples)
    return samples, stats


def collect_winning_combat_dataset(
    seeds: list[int] | tuple[int, ...],
    *,
    assets_dir: str = "data",
    episodes_per_seed: int = 3,
    require_zero_deaths: bool = True,
) -> tuple[list[CombatSample], dict[str, Any]]:
    """Collect outcome-filtered (winning-only) combat transitions on training seeds 0-899."""
    validate_train_seeds(seeds)
    am = AssetManager(assets_dir)
    am.load_all()

    kept_samples: list[CombatSample] = []
    episodes_total = 0
    episodes_won = 0
    episodes_kept = 0

    for s in seeds:
        for ep in range(episodes_per_seed):
            episodes_total += 1
            ep_seed = s * 100 + ep
            level = 3 + ((s + ep) % 12)
            won, deaths, samples = run_combat_episode(am, ep_seed, level=level)
            if won:
                episodes_won += 1
                if not require_zero_deaths or deaths == 0:
                    episodes_kept += 1
                    kept_samples.extend(samples)

    meta = {
        "git_sha": current_git_sha(),
        "train_seeds": list(seeds),
        "episodes_total": episodes_total,
        "episodes_won": episodes_won,
        "episodes_kept": episodes_kept,
        "transitions_kept": len(kept_samples),
    }
    return kept_samples, meta


def save_combat_dataset(path: str | Path, samples: list[CombatSample], meta: dict[str, Any]) -> None:
    """Persist outcome-filtered combat dataset as JSON."""
    payload = {
        "meta": meta,
        "samples": [
            {
                "grid": s.grid,
                "context": s.context,
                "mask": s.mask,
                "action_idx": s.action_idx,
            }
            for s in samples
        ],
    }
    Path(path).write_text(json.dumps(payload), encoding="utf-8")


def load_combat_dataset(path: str | Path) -> tuple[list[CombatSample], dict[str, Any]]:
    """Load outcome-filtered combat dataset from JSON."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    samples = [
        CombatSample(
            grid=row["grid"],
            context=row["context"],
            mask=row["mask"],
            action_idx=int(row["action_idx"]),
        )
        for row in payload["samples"]
    ]
    return samples, dict(payload["meta"])
