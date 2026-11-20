"""Phase 1 Behavioral Cloning trainer and CombatPolicyNet (1-3M params, <500MB VRAM)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from py_exodus.nn.combat_dataset import (
    CombatSample,
    current_git_sha,
    validate_train_seeds,
)
from py_exodus.nn.combat_env import (
    COMBAT_CONTEXT_DIM,
    COMBAT_GRID_CHANNELS,
    COMBAT_GRID_SIZE,
    NUM_COMBAT_ACTIONS,
)

MAX_COMBAT_PARAMS = 3_000_000


class CombatPolicyNet(nn.Module):
    """Compact CNN+MLP policy+value network (~1.1M params) for 11x11 CombatArena.

    v2 (2026-11-20): encoder grew to 11 grid channels + 33 context dims, so
    the conv trunk was rebalanced 64/128/128 -> 48/96/64 to keep the net
    SMALLER than before despite richer inputs — FC head cost scales with
    the final channel count, which is what dominates the parameter budget.
    """

    def __init__(
        self,
        in_channels: int = COMBAT_GRID_CHANNELS,
        context_dim: int = COMBAT_CONTEXT_DIM,
        num_actions: int = NUM_COMBAT_ACTIONS,
    ) -> None:
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_channels, 48, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Conv2d(48, 96, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Conv2d(96, 64, kernel_size=3, padding=1),
            nn.ReLU(),
        )
        flat_dim = 64 * COMBAT_GRID_SIZE * COMBAT_GRID_SIZE  # 7,744
        self.ctx_mlp = nn.Sequential(
            nn.Linear(context_dim, 64),
            nn.ReLU(),
        )
        self.head_trunk = nn.Sequential(
            nn.Linear(flat_dim + 64, 96),
            nn.ReLU(),
            nn.Linear(96, 128),
            nn.ReLU(),
        )
        self.policy_head = nn.Linear(128, num_actions)
        self.value_head = nn.Linear(128, 1)

    def forward(
        self,
        grid: torch.Tensor,
        context: torch.Tensor,
        mask: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Return (masked_logits, value) for batched (grid, context, mask)."""
        conv_feat = self.conv(grid).flatten(start_dim=1)
        ctx_feat = self.ctx_mlp(context)
        hidden = self.head_trunk(torch.cat([conv_feat, ctx_feat], dim=-1))
        logits = self.policy_head(hidden)
        if mask is not None:
            logits = logits.masked_fill(~mask.bool(), -1e9)
        value = self.value_head(hidden).squeeze(-1)
        return logits, value

    def count_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters())


def train_combat_bc(
    samples: list[CombatSample],
    train_seeds: list[int] | tuple[int, ...],
    *,
    epochs: int = 12,
    batch_size: int = 128,
    lr: float = 1e-3,
    val_fraction: float = 0.15,
    device: str | None = None,
) -> tuple[CombatPolicyNet, dict[str, Any]]:
    """Train CombatPolicyNet via masked cross-entropy behavioral cloning."""
    validate_train_seeds(train_seeds)
    if not samples:
        raise ValueError("Cannot train CombatPolicyNet on empty samples list.")

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    grids = torch.tensor([s.grid for s in samples], dtype=torch.float32)
    contexts = torch.tensor([s.context for s in samples], dtype=torch.float32)
    masks = torch.tensor([s.mask for s in samples], dtype=torch.bool)
    actions = torch.tensor([s.action_idx for s in samples], dtype=torch.long)

    n_total = len(samples)
    n_val = max(1, int(n_total * val_fraction)) if n_total >= 5 else 0
    n_train = n_total - n_val

    perm = torch.randperm(n_total, generator=torch.Generator().manual_seed(42))
    train_idx = perm[:n_train]
    val_idx = perm[n_train:] if n_val > 0 else perm[:n_train]

    train_loader = DataLoader(
        TensorDataset(grids[train_idx], contexts[train_idx], masks[train_idx], actions[train_idx]),
        batch_size=min(batch_size, max(1, n_train)),
        shuffle=True,
    )

    model = CombatPolicyNet().to(device)
    param_count = model.count_parameters()
    if param_count > MAX_COMBAT_PARAMS:
        raise RuntimeError(f"CombatPolicyNet exceeds {MAX_COMBAT_PARAMS} params: {param_count}")

    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    criterion = nn.CrossEntropyLoss()

    model.train()
    for _ in range(epochs):
        for b_g, b_c, b_m, b_a in train_loader:
            b_g, b_c, b_m, b_a = b_g.to(device), b_c.to(device), b_m.to(device), b_a.to(device)
            opt.zero_grad()
            logits, _ = model(b_g, b_c, b_m)
            loss = criterion(logits, b_a)
            loss.backward()
            opt.step()

    model.eval()
    with torch.no_grad():
        # Batched forward: the conv stack's activations on the whole val
        # split at once are ~1 GiB+ (2026-11-20 CUDA OOM on a 6 GB card);
        # 512-sample batches stay well inside it.
        eval_idx = val_idx if n_val > 0 else train_idx
        eval_acc_over = max(1, n_val if n_val > 0 else n_train)
        v_correct = 0
        for start in range(0, len(eval_idx), 512):
            sl = slice(start, start + 512)
            v_g = grids[eval_idx[sl]].to(device)
            v_c = contexts[eval_idx[sl]].to(device)
            v_m = masks[eval_idx[sl]].to(device)
            v_logits, _ = model(v_g, v_c, v_m)
            v_correct += int(
                (v_logits.argmax(dim=-1) == actions[eval_idx[sl]].to(device))
                .sum()
                .item()
            )
        val_acc = v_correct / eval_acc_over

    meta = {
        "git_sha": current_git_sha(),
        "train_seeds": list(train_seeds),
        "param_count": param_count,
        "transitions": n_total,
        "val_acc": val_acc,
        "device": device,
    }
    return model, meta


def save_combat_checkpoint(
    path: str | Path,
    model: CombatPolicyNet,
    meta: dict[str, Any],
) -> None:
    """Save CombatPolicyNet weights and provenance metadata."""
    torch.save(
        {
            "meta": dict(meta),
            "state_dict": model.state_dict(),
        },
        Path(path),
    )


def load_combat_checkpoint(
    path: str | Path,
    *,
    device: str = "cpu",
) -> tuple[CombatPolicyNet, dict[str, Any]]:
    """Load CombatPolicyNet checkpoint and metadata."""
    ckpt = torch.load(Path(path), map_location=device, weights_only=False)
    model = CombatPolicyNet().to(device)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    return model, dict(ckpt["meta"])


def evaluate_combat_policy(
    model: CombatPolicyNet | None,
    seeds: list[int] | tuple[int, ...],
    *,
    episodes_per_seed: int = 2,
    assets_dir: str = "data",
    device: str = "cpu",
    max_turns: int = 60,
) -> dict[str, Any]:
    """Evaluate a CombatPolicyNet (or symbolic auto_combat if model is None) on CombatArena episodes."""
    import random
    from py_exodus.assets import AssetManager
    from py_exodus.combat.arena import CombatArena
    from py_exodus.combat.auto_combat import choose_auto_combat_action
    from py_exodus.nn.combat_dataset import (
        _DEFAULT_CONFLICT_MAP_IDS,
        _DEFAULT_CREATURES,
        _make_sample_party,
    )
    from py_exodus.nn.combat_env import encode_combat_state, index_to_action, legal_action_mask
    from py_exodus.world.loader import load_map

    am = AssetManager(assets_dir)
    am.load_all()
    if model is not None:
        model = model.to(device)
        model.eval()

    total = 0
    wins = 0
    total_deaths = 0
    for s in seeds:
        for ep in range(episodes_per_seed):
            total += 1
            ep_seed = s * 100 + ep
            rng = random.Random(ep_seed)
            random.seed(ep_seed)
            level = 3 + ((s + ep) % 12)
            party = _make_sample_party(level=level, rng=rng)
            cmap = load_map(rng.choice(_DEFAULT_CONFLICT_MAP_IDS), am)
            creature_tile = rng.choice(_DEFAULT_CREATURES)
            monster_count = rng.randint(1, 5)
            arena = CombatArena(
                party, cmap, asset_mgr=am, creature_tile=creature_tile, monster_count=monster_count
            )
            scr = type(
                "_Scr",
                (),
                {
                    "trammel_phase": rng.randrange(24),
                    "felucca_phase": rng.randrange(8),
                    "creatures": (),
                },
            )()
            steps = 0
            while not arena.is_finished and steps < max_turns * 4:
                m_idx = arena.active_party_member_idx
                if model is None:
                    action = choose_auto_combat_action(arena, m_idx, asset_mgr=am)
                else:
                    grid, ctx = encode_combat_state(arena, m_idx, screen=scr, asset_mgr=am)
                    mask = legal_action_mask(arena, m_idx, asset_mgr=am)
                    with torch.no_grad():
                        g_t = torch.tensor([grid], dtype=torch.float32, device=device)
                        c_t = torch.tensor([ctx], dtype=torch.float32, device=device)
                        m_t = torch.tensor([mask], dtype=torch.bool, device=device)
                        logits, _ = model(g_t, c_t, m_t)
                        a_idx = int(logits.argmax(dim=-1).item())
                    action = index_to_action(a_idx, arena, m_idx, asset_mgr=am)
                arena.execute_turn(action)
                steps += 1
            if arena.is_finished and arena.is_victory:
                wins += 1
            total_deaths += sum(1 for m in party.members if m.is_dead())

    return {
        "episodes": total,
        "wins": wins,
        "win_rate": wins / max(1, total),
        "ally_deaths": total_deaths,
        "deaths_per_ep": total_deaths / max(1, total),
    }


def evaluate_combat_policy_fullspace(
    model: CombatPolicyNet | None,
    seeds: list[int] | tuple[int, ...],
    *,
    assets_dir: str = "data",
    device: str = "cpu",
    monster_counts: tuple[int, ...] = tuple(range(1, 9)),
    levels: tuple[int, ...] = (3, 6, 9, 12, 16, 20, 25),
    episodes_per_cell: int = 4,
    max_turns: int = 90,
) -> dict[str, Any]:
    """Evaluate (or baseline with ``model=None``) across the full battlefield.

    Cells enumerate every reachable (creature, transport, conflict map,
    monster_count) combination — ship battles, boarding and sea-swimmer
    encounters included — where the phase-1 nets were only ever evaluated
    on land maps. Stats split ship-battle vs land families so an
    out-of-distribution collapse shows up directly.
    """
    import random

    from py_exodus.assets import AssetManager
    from py_exodus.combat.arena import CombatArena
    from py_exodus.combat.auto_combat import choose_auto_combat_action
    from py_exodus.constants import Transport
    from py_exodus.nn.combat_dataset import (
        _make_diverse_party,
        battle_terrain_cells,
        validate_train_seeds,
    )
    from py_exodus.nn.combat_env import (
        encode_combat_state,
        index_to_action,
        legal_action_mask,
    )
    from py_exodus.world.loader import load_map

    # NOTE: no validate_train_seeds here — this evaluates on HOLDOUT seeds
    # (900-999); the validator guards TRAINING collections only.
    am = AssetManager(assets_dir)
    am.load_all()
    if model is not None:
        model = model.to(device)
        model.eval()
    cells = battle_terrain_cells(monster_counts=monster_counts)

    by_family = {
        "land": {"episodes": 0, "wins": 0, "deaths": 0},
        "ship": {"episodes": 0, "wins": 0, "deaths": 0},
    }
    ep_i = 0
    for tile, transport, cmap_id, count in cells:
        for k in range(episodes_per_cell):
            ep_i += 1
            ep_seed = seeds[ep_i % len(seeds)] * 1000 + (ep_i // len(seeds)) + k
            rng = random.Random(ep_seed)
            random.seed(ep_seed)
            level = levels[ep_i % len(levels)]
            party = _make_diverse_party(level=level, rng=rng)
            party.transport = transport
            random.seed(ep_seed)
            arena = CombatArena(
                party, load_map(cmap_id, am), asset_mgr=am,
                creature_tile=tile, monster_count=count,
            )
            scr = type(
                "_Scr",
                (),
                {
                    "trammel_phase": rng.randrange(24),
                    "felucca_phase": rng.randrange(8),
                    "creatures": (),
                },
            )()
            steps = 0
            while not arena.is_finished and steps < max_turns * 4:
                m_idx = arena.active_party_member_idx
                if model is None:
                    action = choose_auto_combat_action(arena, m_idx, asset_mgr=am)
                else:
                    grid, ctx = encode_combat_state(arena, m_idx, screen=scr, asset_mgr=am)
                    mask = legal_action_mask(arena, m_idx, asset_mgr=am)
                    with torch.no_grad():
                        g_t = torch.tensor([grid], dtype=torch.float32, device=device)
                        c_t = torch.tensor([ctx], dtype=torch.float32, device=device)
                        m_t = torch.tensor([mask], dtype=torch.bool, device=device)
                        logits, _ = model(g_t, c_t, m_t)
                        a_idx = int(logits.argmax(dim=-1).item())
                    action = index_to_action(a_idx, arena, m_idx, asset_mgr=am)
                arena.execute_turn(action)
                steps += 1
            fam = "ship" if transport == Transport.SHIP else "land"
            won = bool(arena.is_finished and arena.is_victory)
            slot = by_family[fam]
            slot["episodes"] += 1
            slot["wins"] += 1 if won else 0
            slot["deaths"] += sum(1 for m in party.members if m.is_dead())

    total_eps = sum(f["episodes"] for f in by_family.values())
    total_wins = sum(f["wins"] for f in by_family.values())
    report = {"episodes": total_eps, "wins": total_wins}
    for fam, slot in by_family.items():
        report[fam] = {
            "win_rate": slot["wins"] / max(1, slot["episodes"]),
            "deaths_per_ep": slot["deaths"] / max(1, slot["episodes"]),
            "episodes": slot["episodes"],
        }
    return report
