"""Unit tests for Phase 3 MacroCriticNet, milestone returns, and disagreement mining."""
from __future__ import annotations

import json

import pytest

from py_exodus.autoplay.features import MACRO_FEATURE_NAMES
from py_exodus.constants import Profession, Race
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.nn.macro_critic import (
    MAX_MACRO_PARAMS,
    DisagreementLogger,
    MacroCriticNet,
    load_macro_checkpoint,
    save_macro_checkpoint,
    train_macro_bc,
)
from py_exodus.nn.macro_dataset import (
    GOAL_LIST,
    MacroSample,
    collect_winning_macro_trajectories,
    compute_milestone_score,
)


def test_macro_critic_net_param_budget():
    assert MacroCriticNet().count_parameters() <= MAX_MACRO_PARAMS


def test_compute_milestone_score_ignores_raw_xp_and_gold():
    p_poor = Party()
    p_poor.add_member(Character("A", "M", Race.ELF, Profession.THIEF, gold=0, exp=0))
    p_rich = Party()
    p_rich.add_member(Character("A", "M", Race.ELF, Profession.THIEF, gold=9999, exp=9999))
    assert compute_milestone_score(p_poor) == compute_milestone_score(p_rich)


def test_disagreement_logger_exports_only_nn_won_clashes(tmp_path):
    logger = DisagreementLogger()
    logger.log(seed=1, step=10, map_id=0, pos=(10, 10), nn_goal="buy_food", sym_goal="grind_and_level")
    logger.finalize_episode(seed=1, outcome="WON")
    logger.log(seed=2, step=20, map_id=0, pos=(12, 12), nn_goal="buy_keys", sym_goal="grind_and_level")
    logger.finalize_episode(seed=2, outcome="WIPED")
    out = tmp_path / "clashes.json"
    count = logger.export_nn_won_disagreements(out)
    rows = json.loads(out.read_text(encoding="utf-8"))
    assert count == 1 and len(rows) == 1 and rows[0]["seed"] == 1


def test_collect_winning_macro_trajectories_rejects_holdout_seed():
    with pytest.raises(ValueError):
        collect_winning_macro_trajectories([900], max_steps=10)


def test_train_macro_bc_and_checkpoint_roundtrip(tmp_path):
    n_f = len(MACRO_FEATURE_NAMES)
    n_g = len(GOAL_LIST)
    samples = [
        MacroSample(
            features=[float(i % 5)] * n_f,
            legal_mask=[True] * n_g,
            goal_idx=i % n_g,
            milestone_return=1.5,
        )
        for i in range(12)
    ]
    model, meta = train_macro_bc(samples, [1, 2], epochs=3, device="cpu")
    ckpt = tmp_path / "macro_bc.pt"
    save_macro_checkpoint(ckpt, model, meta)
    loaded, loaded_meta = load_macro_checkpoint(ckpt, device="cpu")
    assert loaded.count_parameters() == loaded_meta["param_count"] and "git_sha" in loaded_meta
