"""Unit tests for Phase 2 Combat PPO fine-tuning and provenance gates."""
from __future__ import annotations

import pytest
import torch

from py_exodus.nn.combat_ppo import (
    compute_gae,
    train_combat_ppo,
    verify_checkpoint_sha,
)


def test_verify_checkpoint_sha_rejects_mismatch():
    with pytest.raises(RuntimeError):
        verify_checkpoint_sha({"git_sha": "0000000000000000000000000000000000000000"})


def test_train_combat_ppo_rejects_holdout_seed():
    with pytest.raises(ValueError):
        train_combat_ppo([0, 900], iterations=1, episodes_per_iter=2)


def test_compute_gae_respects_episode_boundary():
    rewards = [1.0, 1.0]
    values = torch.tensor([0.5, 0.5], dtype=torch.float32)
    dones = [True, True]
    returns, _ = compute_gae(rewards, values, dones, gamma=0.99, gae_lambda=0.95)
    assert torch.allclose(returns, torch.tensor([1.0, 1.0]))


def test_train_combat_ppo_runs_and_records_git_sha():
    model, meta = train_combat_ppo([1, 2], iterations=1, episodes_per_iter=2, device="cpu")
    assert meta["ppo_steps"] > 0 and "git_sha" in meta and model.count_parameters() > 0
