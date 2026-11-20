"""Unit tests for Phase 3 Macro RL (PPO + KL-anchored fine-tuning)."""
from __future__ import annotations

import pytest
import torch

from py_exodus.nn.macro_critic import MacroCriticNet, save_macro_checkpoint
from py_exodus.nn.macro_rl import (
    MacroTransition,
    collect_macro_rollouts,
    compute_gae_returns,
    train_macro_rl,
)


def test_macro_rl_rejects_holdout_seeds(tmp_path):
    ckpt = tmp_path / "macro.pt"
    save_macro_checkpoint(ckpt, MacroCriticNet(), {"git_sha": "test"})
    with pytest.raises(ValueError, match="900"):
        collect_macro_rollouts([900], ckpt, max_steps=10)
    with pytest.raises(ValueError, match="905"):
        train_macro_rl(ckpt, [905], iterations=1, episodes_per_iter=1, max_steps=10, workers=1)


def test_compute_gae_returns_respects_episode_boundaries():
    trans = [
        MacroTransition([0.0] * 35, [True] * 18, 0, -1.0, 1.0, 0.5, False),
        MacroTransition([0.0] * 35, [True] * 18, 0, -1.0, 2.0, 1.0, True),
        MacroTransition([0.0] * 35, [True] * 18, 0, -1.0, 0.5, 0.2, True),
    ]
    adv, ret = compute_gae_returns(trans, gamma=1.0, lam=1.0)
    assert pytest.approx(ret[2].item(), abs=1e-5) == 0.5
    assert pytest.approx(ret[1].item(), abs=1e-5) == 2.0
    assert pytest.approx(ret[0].item(), abs=1e-5) == 3.0


def test_train_macro_rl_smoke(tmp_path):
    bc_ckpt = tmp_path / "macro_bc.pt"
    rl_ckpt = tmp_path / "macro_rl.pt"
    save_macro_checkpoint(bc_ckpt, MacroCriticNet(), {"git_sha": "test"})

    model, meta = train_macro_rl(
        bc_ckpt,
        [0, 1],
        out_ckpt=rl_ckpt,
        iterations=1,
        episodes_per_iter=2,
        max_steps=40,
        workers=1,
        ppo_epochs=1,
        batch_size=8,
        device="cpu",
    )
    assert rl_ckpt.exists()
    assert meta["transitions"] > 0
    assert len(meta["history"]) == 1
    assert isinstance(model, MacroCriticNet)
    torch.cuda.empty_cache() if torch.cuda.is_available() else None
