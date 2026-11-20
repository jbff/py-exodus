"""Full-game macro trajectory collector with milestone-shaped returns for Phase 3."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import random
from typing import Any

from py_exodus.assets import AssetManager
from py_exodus.autoplay.controller import AutoPlayController
from py_exodus.autoplay.features import (
    MACRO_FEATURE_NAMES,
    extract_macro_features,
    macro_feature_vector,
)
from py_exodus.autoplay.planner import Goal, evaluate_goal, score_goals
from py_exodus.constants import ArmorType, Profession, Race, WeaponType
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.nn.combat_dataset import current_git_sha, validate_train_seeds
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.state_machine import StateMachine

GOAL_LIST: tuple[Goal, ...] = tuple(Goal)
GOAL_TO_INDEX: dict[Goal, int] = {g: i for i, g in enumerate(GOAL_LIST)}
INDEX_TO_GOAL: dict[int, Goal] = {i: g for i, g in enumerate(GOAL_LIST)}

_STEP_PENALTY = -0.0001
_VICTORY_BONUS = 5.0
_WIPE_PENALTY = -5.0


@dataclass
class MacroSample:
    """Single encoded macro decision sample (features, legal goal mask, goal_idx, return)."""

    features: list[float]
    legal_mask: list[bool]
    goal_idx: int
    milestone_return: float


def compute_milestone_score(party: Party) -> float:
    """Compute cumulative milestone progress score (marks, exotics, cards, Exodus).

    Never uses raw XP or gold totals.
    """
    living = [m for m in party.members if not m.is_dead()]
    score = 0.0
    if living:
        for i in range(4):
            if any(m.marks[i] > 0 for m in living):
                score += 0.5
        for i in range(4):
            if any(m.cards[i] > 0 for m in living):
                score += 0.5
        has_exotics = all(
            (m.weapon == WeaponType.EXOTIC or m.weapons.get(WeaponType.EXOTIC, 0) > 0)
            and (m.armor == ArmorType.EXOTIC or m.armors.get(ArmorType.EXOTIC, 0) > 0)
            for m in party.members
        )
        if has_exotics:
            score += 0.5
    status = getattr(party, "exodus_cards_status", 0)
    for bit in range(4):
        if status & (1 << bit):
            score += 1.0
    if getattr(party, "exodus_defeated", 0) > 0:
        score += _VICTORY_BONUS
    return score


def legal_goal_mask(party: Party, map_id: int = 0, screen=None) -> list[bool]:
    """Return boolean mask over GOAL_LIST for goals currently eligible in score_goals."""
    scores = score_goals(party, map_id=map_id, screen=screen)
    mask = [scores[g] > -1e8 for g in GOAL_LIST]
    if not any(mask):
        mask[GOAL_TO_INDEX[Goal.GRIND_AND_LEVEL]] = True
    return mask


def collect_winning_macro_trajectories(
    seeds: list[int] | tuple[int, ...],
    *,
    max_steps: int = 160_000,
    sample_stride: int = 10,
    assets_dir: str = "data",
    gamma: float = 0.999,
) -> tuple[list[MacroSample], dict[str, Any]]:
    """Run training seeds [0, 899] and keep macro trajectories from WON runs only."""
    validate_train_seeds(seeds)
    am = AssetManager(assets_dir)
    am.load_all()

    kept_samples: list[MacroSample] = []
    won_seeds: list[int] = []

    for seed in seeds:
        random.seed(seed)
        party = Party()
        party.add_member(Character("SHADOW", "M", Race.ELF, Profession.THIEF, strength=15, dexterity=25, gold=150))
        party.add_member(Character("GRUMM", "M", Race.DWARF, Profession.FIGHTER, strength=25, dexterity=15, gold=150))
        party.add_member(Character("SERENA", "F", Race.BOBIT, Profession.CLERIC, wisdom=25, strength=15, gold=150))
        party.add_member(Character("ZIRCON", "M", Race.FUZZY, Profession.WIZARD, intelligence=25, strength=15, gold=150))
        party.x, party.y = 44, 20

        sm = StateMachine(asset_mgr=am, audio=None)
        ow = OverworldScreen(party=party, asset_mgr=am)
        sm.set_screen(ow)
        ctrl = AutoPlayController(enabled=True)

        ep_rows: list[tuple[list[float], list[bool], int, float]] = []
        prev_mscore = compute_milestone_score(party)
        won = False

        for s in range(max_steps):
            scr = sm.current_screen
            cur_map_id = getattr(getattr(scr, "game_map", None), "id", getattr(party, "map_id", 0))
            if s % sample_stride == 0 and type(scr).__name__ in ("OverworldScreen", "TownScreen"):
                feats = extract_macro_features(party, map_id=cur_map_id, screen=scr)
                vec = macro_feature_vector(feats)
                mask = legal_goal_mask(party, map_id=cur_map_id, screen=scr)
                g_idx = GOAL_TO_INDEX[evaluate_goal(party, cur_map_id)]
                cur_mscore = compute_milestone_score(party)
                delta_r = (cur_mscore - prev_mscore) + _STEP_PENALTY * sample_stride
                prev_mscore = cur_mscore
                ep_rows.append((vec, mask, g_idx, delta_r))

            ctrl.step(sm)
            sm.update(0.05)

            if all(m.is_dead() for m in party.members):
                break
            if getattr(party, "exodus_defeated", 0) > 0:
                won = True
                break

        if won and ep_rows:
            won_seeds.append(seed)
            # Add terminal victory reward to last sample and compute discounted returns
            last_v, last_m, last_g, last_r = ep_rows[-1]
            ep_rows[-1] = (last_v, last_m, last_g, last_r + _VICTORY_BONUS)
            running = 0.0
            ep_samples: list[MacroSample] = []
            for vec, mask, g_idx, rew in reversed(ep_rows):
                running = rew + gamma * running
                ep_samples.append(
                    MacroSample(
                        features=vec,
                        legal_mask=mask,
                        goal_idx=g_idx,
                        milestone_return=running,
                    )
                )
            ep_samples.reverse()
            kept_samples.extend(ep_samples)

    meta = {
        "git_sha": current_git_sha(),
        "feature_names": list(MACRO_FEATURE_NAMES),
        "train_seeds": list(seeds),
        "won_seeds": won_seeds,
        "transitions_kept": len(kept_samples),
    }
    return kept_samples, meta


def save_macro_dataset(path: str | Path, samples: list[MacroSample], meta: dict[str, Any]) -> None:
    """Persist macro BC dataset to JSON."""
    payload = {
        "meta": meta,
        "samples": [
            {
                "features": s.features,
                "legal_mask": s.legal_mask,
                "goal_idx": s.goal_idx,
                "milestone_return": s.milestone_return,
            }
            for s in samples
        ],
    }
    Path(path).write_text(json.dumps(payload), encoding="utf-8")


def load_macro_dataset(path: str | Path) -> tuple[list[MacroSample], dict[str, Any]]:
    """Load macro BC dataset from JSON."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    samples = [
        MacroSample(
            features=row["features"],
            legal_mask=row["legal_mask"],
            goal_idx=int(row["goal_idx"]),
            milestone_return=float(row["milestone_return"]),
        )
        for row in payload["samples"]
    ]
    return samples, dict(payload["meta"])
