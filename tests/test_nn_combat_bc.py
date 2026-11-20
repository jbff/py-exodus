"""Unit tests for Phase 1 combat dataset collection and behavioral cloning."""
from __future__ import annotations

import pytest

from py_exodus.nn.combat_bc import (
    MAX_COMBAT_PARAMS,
    CombatPolicyNet,
    load_combat_checkpoint,
    save_combat_checkpoint,
    train_combat_bc,
)
from py_exodus.nn.combat_dataset import (
    collect_winning_combat_dataset,
    load_combat_dataset,
    save_combat_dataset,
    validate_train_seeds,
)


def test_seed_hygiene_rejects_holdout_seed():
    with pytest.raises(ValueError):
        validate_train_seeds([0, 900])


def test_combat_policy_net_param_budget():
    assert CombatPolicyNet().count_parameters() <= MAX_COMBAT_PARAMS


def test_collect_winning_combat_dataset_records_samples_and_meta(tmp_path):
    samples, meta = collect_winning_combat_dataset([1, 2], episodes_per_seed=2)
    out_path = tmp_path / "combat_ds.json"
    save_combat_dataset(out_path, samples, meta)
    loaded_samples, loaded_meta = load_combat_dataset(out_path)
    assert len(loaded_samples) > 0 and loaded_meta["episodes_kept"] <= loaded_meta["episodes_won"]


def test_train_combat_bc_and_checkpoint_roundtrip(tmp_path):
    samples, _ = collect_winning_combat_dataset([1, 2, 3], episodes_per_seed=2)
    model, meta = train_combat_bc(samples, [1, 2, 3], epochs=3)
    ckpt_path = tmp_path / "combat_bc.pt"
    save_combat_checkpoint(ckpt_path, model, meta)
    loaded, loaded_meta = load_combat_checkpoint(ckpt_path)
    assert loaded.count_parameters() == loaded_meta["param_count"] and "git_sha" in loaded_meta
