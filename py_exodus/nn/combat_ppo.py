"""Phase 2 Combat PPO fine-tuning for CombatPolicyNet on 11x11 CombatArena episodes."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random
from typing import Any

import torch
from torch import nn
from torch.distributions import Categorical

from py_exodus.assets import AssetManager
from py_exodus.combat.arena import CombatArena
from py_exodus.nn.combat_bc import (
    MAX_COMBAT_PARAMS,
    CombatPolicyNet,
    load_combat_checkpoint,
    save_combat_checkpoint,
)
from py_exodus.nn.combat_dataset import (
    _make_diverse_party,
    battle_terrain_cells,
    current_git_sha,
    validate_train_seeds,
)


def _battlefield_cells() -> list[tuple[str, Transport, int, int]]:
    """Cached enumeration of the full space cells for rollout sampling."""
    cache = getattr(_battlefield_cells, "_cache", None)
    if cache is None:
        cache = list(battle_terrain_cells())
        _battlefield_cells._cache = cache
    return cache
from py_exodus.nn.combat_env import (
    encode_combat_state,
    index_to_action,
    legal_action_mask,
)
from py_exodus.world.loader import load_map

VICTORY_REWARD = 1.0
WIPE_PENALTY = -1.0
ALLY_DEATH_PENALTY = -0.25
ENEMY_DEFEATED_BONUS = 0.1
STEP_PENALTY = -0.005


@dataclass
class CombatRolloutBatch:
    """Flattened PPO rollout batch from CombatArena episodes."""

    grids: torch.Tensor
    contexts: torch.Tensor
    masks: torch.Tensor
    actions: torch.Tensor
    logprobs: torch.Tensor
    values: torch.Tensor
    rewards: list[float]
    dones: list[bool]
    episodes: int
    wins: int
    ally_deaths: int


def verify_checkpoint_sha(meta: dict[str, Any], *, allow_mismatch: bool = False) -> None:
    """Refuse to resume/mix rollouts across untagged engine/controller commit changes."""
    if allow_mismatch:
        return
    ckpt_sha = meta.get("git_sha")
    head_sha = current_git_sha()
    if ckpt_sha and head_sha != "unknown" and ckpt_sha != head_sha:
        raise RuntimeError(
            f"Checkpoint git_sha {ckpt_sha!r} != current HEAD {head_sha!r}; "
            "refusing to mix rollouts across untagged controller/engine changes."
        )


def compute_gae(
    rewards: list[float],
    values: torch.Tensor,
    dones: list[bool],
    *,
    gamma: float = 0.99,
    gae_lambda: float = 0.95,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Compute Generalized Advantage Estimation returns and advantages."""
    n = len(rewards)
    advantages = torch.zeros(n, dtype=torch.float32)
    last_gae = 0.0
    for t in reversed(range(n)):
        next_nonterminal = 0.0 if dones[t] else 1.0
        next_val = 0.0 if (t + 1 >= n or dones[t]) else float(values[t + 1].item())
        delta = rewards[t] + gamma * next_val * next_nonterminal - float(values[t].item())
        last_gae = delta + gamma * gae_lambda * next_nonterminal * last_gae
        advantages[t] = last_gae
    returns = advantages + values.cpu()
    return returns, advantages


def collect_ppo_rollouts(
    model: CombatPolicyNet,
    am: AssetManager,
    seeds: list[int] | tuple[int, ...],
    *,
    episodes_per_batch: int = 32,
    rng_seed: int = 0,
    max_turns: int = 60,
    device: str = "cpu",
) -> CombatRolloutBatch:
    """Roll out CombatArena episodes using the current policy on training seeds."""
    validate_train_seeds(seeds)
    model.eval()
    rng = random.Random(rng_seed)

    grids: list[list[list[list[float]]]] = []
    contexts: list[list[float]] = []
    masks: list[list[bool]] = []
    actions: list[int] = []
    logprobs: list[float] = []
    values: list[float] = []
    rewards: list[float] = []
    dones: list[bool] = []

    wins = 0
    total_deaths = 0

    for ep in range(episodes_per_batch):
        s = rng.choice(seeds)
        ep_seed = s * 1000 + rng.randrange(1000)
        ep_rng = random.Random(ep_seed)
        random.seed(ep_seed)
        level = 3 + ((s + ep) % 12)
        party = _make_diverse_party(level=level, rng=ep_rng)
        # Full battlefield sampling (v3, 2026-11-20): match the rollout env
        # to the collector/evaluator space — every reachable (creature,
        # transport, map, count) cell — or PPO would erode the ship-battle
        # and nuke-spell skills BC just learned back toward land-only
        # (the bug family that caused the original serpent loop).
        creature_tile, transport, cmap_id, monster_count = ep_rng.choice(
            _battlefield_cells()
        )
        party.transport = transport
        cmap = load_map(cmap_id, am)
        arena = CombatArena(
            party, cmap, asset_mgr=am, creature_tile=creature_tile, monster_count=monster_count
        )
        scr = type(
            "_Scr",
            (),
            {
                "trammel_phase": ep_rng.randrange(24),
                "felucca_phase": ep_rng.randrange(8),
                "creatures": (),
            },
        )()

        prev_dead_allies = sum(1 for m in party.members if m.is_dead())
        prev_dead_monsters = sum(1 for m in arena.monsters if m.is_dead)
        ep_start_idx = len(rewards)
        steps = 0

        while not arena.is_finished and steps < max_turns * 4:
            m_idx = arena.active_party_member_idx
            grid, ctx = encode_combat_state(arena, m_idx, screen=scr, asset_mgr=am)
            mask = legal_action_mask(arena, m_idx, asset_mgr=am)
            with torch.no_grad():
                g_t = torch.tensor([grid], dtype=torch.float32, device=device)
                c_t = torch.tensor([ctx], dtype=torch.float32, device=device)
                m_t = torch.tensor([mask], dtype=torch.bool, device=device)
                logits, val = model(g_t, c_t, m_t)
                dist = Categorical(logits=logits)
                a_t = dist.sample()
                lp_t = dist.log_prob(a_t)

            a_idx = int(a_t.item())
            arena.execute_turn(index_to_action(a_idx, arena, m_idx, asset_mgr=am))

            cur_dead_allies = sum(1 for m in party.members if m.is_dead())
            cur_dead_monsters = sum(1 for m in arena.monsters if m.is_dead)
            step_r = (
                STEP_PENALTY
                + (cur_dead_allies - prev_dead_allies) * ALLY_DEATH_PENALTY
                + (cur_dead_monsters - prev_dead_monsters) * ENEMY_DEFEATED_BONUS
            )
            prev_dead_allies = cur_dead_allies
            prev_dead_monsters = cur_dead_monsters

            grids.append(grid)
            contexts.append(ctx)
            masks.append(mask)
            actions.append(a_idx)
            logprobs.append(float(lp_t.item()))
            values.append(float(val.item()))
            rewards.append(step_r)
            dones.append(False)
            steps += 1

        if len(rewards) > ep_start_idx:
            if arena.is_finished and arena.is_victory:
                rewards[-1] += VICTORY_REWARD
                wins += 1
            elif all(m.is_dead() for m in party.members):
                rewards[-1] += WIPE_PENALTY
            dones[-1] = True
        total_deaths += sum(1 for m in party.members if m.is_dead())

    return CombatRolloutBatch(
        grids=torch.tensor(grids, dtype=torch.float32),
        contexts=torch.tensor(contexts, dtype=torch.float32),
        masks=torch.tensor(masks, dtype=torch.bool),
        actions=torch.tensor(actions, dtype=torch.long),
        logprobs=torch.tensor(logprobs, dtype=torch.float32),
        values=torch.tensor(values, dtype=torch.float32),
        rewards=rewards,
        dones=dones,
        episodes=episodes_per_batch,
        wins=wins,
        ally_deaths=total_deaths,
    )


def ppo_update(
    model: CombatPolicyNet,
    optimizer: torch.optim.Optimizer,
    batch: CombatRolloutBatch,
    *,
    ppo_epochs: int = 4,
    minibatch_size: int = 128,
    clip_eps: float = 0.1,
    vf_coef: float = 0.5,
    ent_coef: float = 0.002,
    critic_only: bool = False,
    device: str = "cpu",
) -> dict[str, float]:
    """Run clipped PPO gradient updates over a collected CombatRolloutBatch."""
    returns, advantages = compute_gae(batch.rewards, batch.values, batch.dones)
    if advantages.numel() > 1:
        advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

    n = batch.actions.size(0)
    if n == 0:
        return {"policy_loss": 0.0, "value_loss": 0.0}

    model.train()
    last_pi_loss = 0.0
    last_v_loss = 0.0
    for _ in range(ppo_epochs):
        perm = torch.randperm(n)
        for start in range(0, n, minibatch_size):
            idx = perm[start : start + minibatch_size]
            b_g = batch.grids[idx].to(device)
            b_c = batch.contexts[idx].to(device)
            b_m = batch.masks[idx].to(device)
            b_a = batch.actions[idx].to(device)
            b_old_lp = batch.logprobs[idx].to(device)
            b_adv = advantages[idx].to(device)
            b_ret = returns[idx].to(device)

            logits, vals = model(b_g, b_c, b_m)
            dist = Categorical(logits=logits)
            new_lp = dist.log_prob(b_a)
            entropy = dist.entropy().mean()

            ratio = torch.exp(new_lp - b_old_lp)
            surr1 = ratio * b_adv
            surr2 = torch.clamp(ratio, 1.0 - clip_eps, 1.0 + clip_eps) * b_adv
            pi_loss = -torch.min(surr1, surr2).mean()
            v_loss = nn.functional.mse_loss(vals, b_ret)
            loss = v_loss if critic_only else (pi_loss + vf_coef * v_loss - ent_coef * entropy)

            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 0.5)
            optimizer.step()

            last_pi_loss = float(pi_loss.item())
            last_v_loss = float(v_loss.item())

    return {"policy_loss": last_pi_loss, "value_loss": last_v_loss}


def train_combat_ppo(
    train_seeds: list[int] | tuple[int, ...],
    *,
    init_checkpoint: str | Path | None = None,
    allow_sha_mismatch: bool = False,
    iterations: int = 20,
    episodes_per_iter: int = 32,
    lr: float = 2e-4,
    assets_dir: str = "data",
    device: str | None = None,
) -> tuple[CombatPolicyNet, dict[str, Any]]:
    """Fine-tune CombatPolicyNet with PPO on training seeds [0, 899]."""
    validate_train_seeds(train_seeds)
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    if init_checkpoint is not None:
        model, ckpt_meta = load_combat_checkpoint(init_checkpoint, device=device)
        verify_checkpoint_sha(ckpt_meta, allow_mismatch=allow_sha_mismatch)
    else:
        model = CombatPolicyNet().to(device)

    param_count = model.count_parameters()
    if param_count > MAX_COMBAT_PARAMS:
        raise RuntimeError(f"CombatPolicyNet exceeds {MAX_COMBAT_PARAMS} params: {param_count}")

    am = AssetManager(assets_dir)
    am.load_all()
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    critic_opt = torch.optim.AdamW(model.value_head.parameters(), lr=1e-3, weight_decay=1e-4)
    critic_warmup_iters = min(3, max(0, iterations - 1)) if init_checkpoint is not None else 0

    total_steps = 0
    total_episodes = 0
    total_wins = 0
    for it in range(iterations):
        batch = collect_ppo_rollouts(
            model,
            am,
            train_seeds,
            episodes_per_batch=episodes_per_iter,
            rng_seed=it + 1,
            device=device,
        )
        if it < critic_warmup_iters:
            ppo_update(model, critic_opt, batch, critic_only=True, device=device)
        else:
            ppo_update(model, optimizer, batch, device=device)
        total_steps += len(batch.rewards)
        total_episodes += batch.episodes
        total_wins += batch.wins

    meta = {
        "git_sha": current_git_sha(),
        "train_seeds": list(train_seeds),
        "param_count": param_count,
        "ppo_iterations": iterations,
        "ppo_steps": total_steps,
        "train_win_rate": total_wins / max(1, total_episodes),
        "device": device,
    }
    return model, meta
