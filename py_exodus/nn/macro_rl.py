"""Macro RL (PPO + KL-anchored value-weighted fine-tuning) for MacroCriticNet."""
from __future__ import annotations

from dataclasses import dataclass
import multiprocessing as mp
from pathlib import Path
import random
import tempfile
from typing import Any

import torch
from torch import nn
from torch.distributions import Categorical
from torch.utils.data import DataLoader, TensorDataset

from py_exodus.assets import AssetManager
from py_exodus.autoplay.controller import AutoPlayController
from py_exodus.autoplay.features import extract_macro_features, macro_feature_vector
import py_exodus.autoplay.planner as planner_mod
from py_exodus.constants import Profession, Race
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.nn.combat_bc import load_combat_checkpoint
from py_exodus.nn.combat_dataset import current_git_sha, validate_train_seeds
from py_exodus.nn.combat_env import encode_combat_state, index_to_action, legal_action_mask
from py_exodus.nn.macro_critic import (
    MAX_MACRO_PARAMS,
    MacroCriticNet,
    load_macro_checkpoint,
    save_macro_checkpoint,
)
from py_exodus.nn.macro_dataset import (
    GOAL_LIST,
    INDEX_TO_GOAL,
    compute_milestone_score,
    legal_goal_mask,
)
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.state_machine import StateMachine


@dataclass
class MacroTransition:
    """Single macro decision step collected during an RL rollout."""

    features: list[float]
    legal_mask: list[bool]
    goal_idx: int
    log_prob: float
    reward: float
    value: float
    done: bool
    sym_scores: list[float] | None = None


def _policy_dist(
    logits: torch.Tensor,
    mask: torch.Tensor,
    sym_scores: torch.Tensor | None,
    residual_alpha: float,
    score_temp: float,
    temperature: float,
) -> Categorical:
    """Build exact action distribution for either pure-NN or Residual-EV rollouts."""
    if residual_alpha > 0.0 and sym_scores is not None:
        probs = torch.softmax(logits, dim=-1)
        combined = sym_scores + residual_alpha * probs
        policy_logits = (combined / max(1e-3, score_temp)).masked_fill(~mask, -1e9)
        return Categorical(logits=policy_logits)
    return Categorical(logits=logits / max(0.1, temperature))


def _rollout_one_seed(args: tuple[int, str, str | None, int, float, float, float]) -> dict[str, Any]:
    seed, macro_ckpt, combat_ckpt, max_steps, temperature, residual_alpha, score_temp = args
    import pygame

    pygame.init()
    torch.set_num_threads(1)

    am = AssetManager("data")
    am.load_all()
    macro_net = load_macro_checkpoint(macro_ckpt, device="cpu")[0]
    combat_net = load_combat_checkpoint(combat_ckpt, device="cpu")[0] if combat_ckpt else None

    random.seed(seed)
    party = Party()
    party.add_member(Character("SHADOW", "M", Race.ELF, Profession.THIEF, strength=15, dexterity=25, gold=150))
    party.add_member(Character("GRUMM", "M", Race.DWARF, Profession.FIGHTER, strength=25, dexterity=15, gold=150))
    party.add_member(Character("SERENA", "F", Race.BOBIT, Profession.CLERIC, wisdom=25, strength=15, gold=150))
    party.add_member(Character("ZIRCON", "M", Race.FUZZY, Profession.WIZARD, intelligence=25, strength=15, gold=150))
    party.x, party.y = 44, 20

    sm = StateMachine(asset_mgr=am, audio=None)
    sm.set_screen(OverworldScreen(party=party, asset_mgr=am))
    ctrl = AutoPlayController(enabled=True)

    orig_eval = planner_mod.evaluate_goal
    goal_cache: dict[tuple[int, int, int, int], Any] = {}
    transitions: list[MacroTransition] = []

    prev_milestone = compute_milestone_score(party)
    prev_levels = sum(m.level for m in party.members)
    prev_living = sum(1 for m in party.members if not m.is_dead())

    def _accumulate_shaping() -> float:
        nonlocal prev_milestone, prev_levels, prev_living
        cur_milestone = compute_milestone_score(party)
        cur_levels = sum(m.level for m in party.members)
        cur_living = sum(1 for m in party.members if not m.is_dead())
        r = 0.001
        r += 2.0 * max(0.0, cur_milestone - prev_milestone)
        r += 0.1 * max(0, cur_levels - prev_levels)
        if cur_living < prev_living:
            r -= 0.5 * (prev_living - cur_living)
        prev_milestone = cur_milestone
        prev_levels = cur_levels
        prev_living = cur_living
        return r

    step_box = [0]

    def _rl_goal(p: Party, map_id: int | str | None = None):
        scr = sm.current_screen
        if type(scr).__name__ not in ("OverworldScreen", "TownScreen"):
            return orig_eval(p, map_id=map_id)
        mid = getattr(getattr(scr, "game_map", None), "id", getattr(p, "map_id", 0))
        cache_key = (int(mid), p.x, p.y, step_box[0] // 8)
        if cache_key in goal_cache:
            return goal_cache[cache_key]

        if transitions:
            transitions[-1].reward += _accumulate_shaping()

        feats = extract_macro_features(p, map_id=mid, screen=scr)
        vec = macro_feature_vector(feats)
        mask = legal_goal_mask(p, map_id=mid, screen=scr)
        sym_vec: list[float] | None = None
        if residual_alpha > 0.0:
            sym_dict = planner_mod.score_goals(p, map_id=mid, screen=scr)
            sym_vec = [float(sym_dict[g]) if m else 0.0 for g, m in zip(GOAL_LIST, mask)]
        with torch.no_grad():
            f_t = torch.tensor([vec], dtype=torch.float32)
            m_t = torch.tensor([mask], dtype=torch.bool)
            s_t = torch.tensor([sym_vec], dtype=torch.float32) if sym_vec is not None else None
            logits, val = macro_net(f_t, m_t)
            dist = _policy_dist(logits, m_t, s_t, residual_alpha, score_temp, temperature)
            idx_t = dist.sample()
            g_idx = int(idx_t.item())
            lp = float(dist.log_prob(idx_t).item())
            v = float(val.item())

        transitions.append(
            MacroTransition(
                features=vec,
                legal_mask=mask,
                goal_idx=g_idx,
                log_prob=lp,
                reward=0.0,
                value=v,
                done=False,
                sym_scores=sym_vec,
            )
        )
        goal = INDEX_TO_GOAL[g_idx]
        goal_cache.clear()
        goal_cache[cache_key] = goal
        return goal

    import py_exodus.autoplay.controller as ctrl_mod
    ctrl_mod.evaluate_goal = _rl_goal
    outcome = "SURVIVED"
    try:
        for s in range(max_steps):
            step_box[0] = s
            scr = sm.current_screen
            if combat_net is not None and type(scr).__name__ == "CombatScreen" and not scr.arena.is_finished:
                arena = scr.arena
                if not arena.is_finished:
                    m_idx = arena.active_party_member_idx
                    grid, ctx = encode_combat_state(arena, m_idx, screen=scr, asset_mgr=am)
                    mask = legal_action_mask(arena, m_idx, asset_mgr=am)
                    with torch.no_grad():
                        logits, _ = combat_net(
                            torch.tensor([grid], dtype=torch.float32),
                            torch.tensor([ctx], dtype=torch.float32),
                            torch.tensor([mask], dtype=torch.bool),
                        )
                        a_idx = int(logits.argmax(dim=-1).item())
                    arena.execute_turn(index_to_action(a_idx, arena, m_idx, asset_mgr=am))
            else:
                ctrl.step(sm)
            sm.update(0.05)

            if all(m.is_dead() for m in party.members):
                outcome = f"WIPED@{s}"
                if transitions:
                    transitions[-1].reward += _accumulate_shaping() - 5.0
                    transitions[-1].done = True
                break
            if getattr(party, "exodus_defeated", 0) > 0:
                outcome = f"WON@{s}"
                if transitions:
                    transitions[-1].reward += _accumulate_shaping() + 15.0
                    transitions[-1].done = True
                break
        else:
            if transitions:
                transitions[-1].reward += _accumulate_shaping()
                transitions[-1].done = True
    finally:
        ctrl_mod.evaluate_goal = orig_eval

    return {
        "seed": seed,
        "outcome": outcome,
        "transitions": transitions,
        "ep_return": sum(t.reward for t in transitions),
    }


def collect_macro_rollouts(
    seeds: list[int] | tuple[int, ...],
    macro_ckpt: str | Path,
    combat_ckpt: str | Path | None = None,
    *,
    max_steps: int = 80_000,
    workers: int = 1,
    temperature: float = 1.0,
    residual_alpha: float = 0.0,
    score_temp: float = 25.0,
) -> tuple[list[MacroTransition], list[dict[str, Any]]]:
    """Collect parallel macro RL rollouts on training seeds only."""
    validate_train_seeds(seeds)
    tasks = [
        (int(s), str(macro_ckpt), str(combat_ckpt) if combat_ckpt else None, max_steps, temperature, residual_alpha, score_temp)
        for s in seeds
    ]
    if workers <= 1 or len(tasks) <= 1:
        episodes = [_rollout_one_seed(t) for t in tasks]
    else:
        with mp.Pool(processes=min(workers, len(tasks))) as pool:
            episodes = pool.map(_rollout_one_seed, tasks)
    all_trans: list[MacroTransition] = []
    summaries: list[dict[str, Any]] = []
    for ep in episodes:
        all_trans.extend(ep["transitions"])
        summaries.append({
            "seed": ep["seed"],
            "outcome": ep["outcome"],
            "steps": len(ep["transitions"]),
            "ep_return": ep["ep_return"],
        })
    return all_trans, summaries


def compute_gae_returns(
    transitions: list[MacroTransition],
    *,
    gamma: float = 0.995,
    lam: float = 0.95,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Compute GAE advantages and discounted returns across packed episodes."""
    n = len(transitions)
    adv = torch.zeros(n, dtype=torch.float32)
    ret = torch.zeros(n, dtype=torch.float32)
    gae = 0.0
    next_val = 0.0
    for i in range(n - 1, -1, -1):
        t = transitions[i]
        mask = 0.0 if t.done else 1.0
        delta = t.reward + gamma * next_val * mask - t.value
        gae = delta + gamma * lam * mask * gae
        adv[i] = gae
        ret[i] = gae + t.value
        next_val = t.value
    return adv, ret


def train_macro_rl(
    macro_ckpt: str | Path,
    train_seeds: list[int] | tuple[int, ...],
    *,
    combat_ckpt: str | Path | None = None,
    out_ckpt: str | Path | None = None,
    iterations: int = 3,
    episodes_per_iter: int = 20,
    max_steps: int = 80_000,
    workers: int = 10,
    temperature: float = 1.0,
    lr: float = 5e-5,
    clip_eps: float = 0.15,
    kl_coef: float = 0.05,
    ent_coef: float = 0.01,
    value_coef: float = 0.5,
    ppo_epochs: int = 4,
    batch_size: int = 256,
    residual_alpha: float = 0.0,
    score_temp: float = 25.0,
    curriculum_seeds: list[int] | tuple[int, ...] | None = None,
    device: str | None = None,
) -> tuple[MacroCriticNet, dict[str, Any]]:
    """Fine-tune MacroCriticNet with KL-anchored PPO over full-game macro rollouts."""
    validate_train_seeds(train_seeds)
    if curriculum_seeds:
        validate_train_seeds(curriculum_seeds)
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    model, bc_meta = load_macro_checkpoint(macro_ckpt, device=device)
    ref_model, _ = load_macro_checkpoint(macro_ckpt, device=device)
    ref_model.eval()
    for p in ref_model.parameters():
        p.requires_grad_(False)

    param_count = model.count_parameters()
    if param_count > MAX_MACRO_PARAMS:
        raise RuntimeError(f"MacroCriticNet exceeds {MAX_MACRO_PARAMS} params: {param_count}")

    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()

    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-2)
    rng = random.Random(42)
    history: list[dict[str, Any]] = []
    total_transitions = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        for it in range(iterations):
            tmp_ckpt = Path(tmpdir) / f"iter_{it}.pt"
            save_macro_checkpoint(tmp_ckpt, model.to("cpu"), bc_meta)
            model.to(device)

            if curriculum_seeds:
                n_cur = episodes_per_iter // 2
                batch_seeds = [rng.choice(curriculum_seeds) for _ in range(n_cur)] + [
                    rng.choice(train_seeds) for _ in range(episodes_per_iter - n_cur)
                ]
            else:
                batch_seeds = [rng.choice(train_seeds) for _ in range(episodes_per_iter)]
            transitions, summaries = collect_macro_rollouts(
                batch_seeds,
                tmp_ckpt,
                combat_ckpt=combat_ckpt,
                max_steps=max_steps,
                workers=workers,
                temperature=temperature,
                residual_alpha=residual_alpha,
                score_temp=score_temp,
            )
            if not transitions:
                continue

            total_transitions += len(transitions)
            adv, ret = compute_gae_returns(transitions)
            adv = (adv - adv.mean()) / adv.std().clamp(min=1e-6)

            feats = torch.tensor([t.features for t in transitions], dtype=torch.float32)
            masks = torch.tensor([t.legal_mask for t in transitions], dtype=torch.bool)
            goals = torch.tensor([t.goal_idx for t in transitions], dtype=torch.long)
            old_lp = torch.tensor([t.log_prob for t in transitions], dtype=torch.float32)
            has_sym = residual_alpha > 0.0 and transitions[0].sym_scores is not None
            sym_t = (
                torch.tensor([t.sym_scores for t in transitions], dtype=torch.float32)
                if has_sym
                else torch.zeros((len(transitions), len(GOAL_LIST)), dtype=torch.float32)
            )

            loader = DataLoader(
                TensorDataset(feats, masks, goals, old_lp, adv, ret, sym_t),
                batch_size=min(batch_size, len(transitions)),
                shuffle=True,
            )
            model.train()
            for _ in range(ppo_epochs):
                for b_f, b_m, b_g, b_olp, b_adv, b_ret, b_sym in loader:
                    b_f = b_f.to(device)
                    b_m = b_m.to(device)
                    b_g = b_g.to(device)
                    b_olp = b_olp.to(device)
                    b_adv = b_adv.to(device)
                    b_ret = b_ret.to(device)
                    b_sym = b_sym.to(device) if has_sym else None

                    logits, vals = model(b_f, b_m)
                    dist = _policy_dist(logits, b_m, b_sym, residual_alpha, score_temp, temperature)
                    new_lp = dist.log_prob(b_g)
                    ratio = torch.exp(new_lp - b_olp)
                    surr1 = ratio * b_adv
                    surr2 = torch.clamp(ratio, 1.0 - clip_eps, 1.0 + clip_eps) * b_adv
                    pol_loss = -torch.min(surr1, surr2).mean()
                    val_loss = nn.functional.mse_loss(vals, b_ret)
                    ent_loss = -dist.entropy().mean()

                    with torch.no_grad():
                        ref_logits, _ = ref_model(b_f, b_m)
                    ref_probs = torch.softmax(ref_logits, dim=-1)
                    cur_log_probs = torch.log_softmax(logits, dim=-1)
                    kl_loss = (ref_probs * (torch.log(ref_probs.clamp(min=1e-8)) - cur_log_probs)).sum(dim=-1).mean()

                    loss = pol_loss + value_coef * val_loss + ent_coef * ent_loss + kl_coef * kl_loss
                    opt.zero_grad()
                    loss.backward()
                    nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    opt.step()

            model.eval()
            wins = sum(1 for s in summaries if s["outcome"].startswith("WON"))
            wipes = sum(1 for s in summaries if s["outcome"].startswith("WIPED"))
            avg_ret = sum(s["ep_return"] for s in summaries) / max(1, len(summaries))
            history.append({
                "iter": it,
                "episodes": len(summaries),
                "wins": wins,
                "wipes": wipes,
                "transitions": len(transitions),
                "avg_return": avg_ret,
            })

    peak_vram_mb = (
        round(torch.cuda.max_memory_allocated() / (1024 * 1024), 2)
        if device == "cuda"
        else 0.0
    )
    meta = {
        "git_sha": current_git_sha(),
        "train_seeds": list(train_seeds),
        "param_count": param_count,
        "transitions": total_transitions,
        "iterations": iterations,
        "history": history,
        "peak_vram_mb": peak_vram_mb,
        "device": device,
    }
    if out_ckpt is not None:
        save_macro_checkpoint(out_ckpt, model.to("cpu"), meta)
        model.to(device)
    return model, meta
