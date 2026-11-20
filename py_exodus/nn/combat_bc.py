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
    """Compact CNN+MLP policy+value network (~1.45M params) for 11x11 CombatArena."""

    def __init__(
        self,
        in_channels: int = COMBAT_GRID_CHANNELS,
        context_dim: int = COMBAT_CONTEXT_DIM,
        num_actions: int = NUM_COMBAT_ACTIONS,
    ) -> None:
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_channels, 64, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Conv2d(128, 128, kernel_size=3, padding=1),
            nn.ReLU(),
        )
        flat_dim = 128 * COMBAT_GRID_SIZE * COMBAT_GRID_SIZE  # 15,488
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
        v_g = grids[val_idx].to(device)
        v_c = contexts[val_idx].to(device)
        v_m = masks[val_idx].to(device)
        v_a = actions[val_idx].to(device)
        v_logits, _ = model(v_g, v_c, v_m)
        val_acc = float((v_logits.argmax(dim=-1) == v_a).float().mean().item())

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
