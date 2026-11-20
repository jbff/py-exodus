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
from py_exodus.constants import ArmorType, Profession, Race, WeaponType
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
