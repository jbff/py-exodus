"""Phase 3 Macro Critic & BC warm-start policy (1-5M params, <500MB VRAM)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from py_exodus.autoplay.features import MACRO_FEATURE_NAMES
from py_exodus.nn.combat_dataset import current_git_sha, validate_train_seeds
from py_exodus.nn.macro_dataset import GOAL_LIST, MacroSample

MAX_MACRO_PARAMS = 5_000_000


class MacroCriticNet(nn.Module):
    """Residual MLP macro policy + value critic (~1.3M params) over MACRO_FEATURE_NAMES."""

    def __init__(
        self,
        in_features: int = len(MACRO_FEATURE_NAMES),
        num_goals: int = len(GOAL_LIST),
        hidden_dim: int = 768,
    ) -> None:
        super().__init__()
        self.register_buffer("feat_mean", torch.zeros(in_features))
        self.register_buffer("feat_std", torch.ones(in_features))
        self.in_proj = nn.Sequential(
            nn.Linear(in_features, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.SiLU(),
        )
        self.block1 = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.SiLU(),
            nn.Dropout(0.1),
        )
        self.block2 = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.SiLU(),
            nn.Dropout(0.1),
        )
        self.policy_head = nn.Linear(hidden_dim, num_goals)
        self.value_head = nn.Linear(hidden_dim, 1)

    def forward(
        self,
        features: torch.Tensor,
        legal_mask: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Return (masked_goal_logits, milestone_value)."""
        normed = (features - self.feat_mean) / self.feat_std.clamp(min=1e-6)
        h = self.in_proj(normed)
        h = h + self.block1(h)
        h = h + self.block2(h)
        logits = self.policy_head(h)
        if legal_mask is not None:
            logits = logits.masked_fill(~legal_mask.bool(), -1e9)
        value = self.value_head(h).squeeze(-1)
        return logits, value

    def count_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters())


@dataclass
class DisagreementEvent:
    """Single logged clash where NN macro goal differed from symbolic planner."""

    seed: int
    step: int
    map_id: int
    pos: tuple[int, int]
    nn_goal: str
    sym_goal: str
    outcome: str = "pending"


class DisagreementLogger:
    """Record NN-vs-symbolic goal clashes and export NN-won clashes for rule review."""

    def __init__(self) -> None:
        self.events: list[DisagreementEvent] = []

    def log(
        self,
        *,
        seed: int,
        step: int,
        map_id: int,
        pos: tuple[int, int],
        nn_goal: str,
        sym_goal: str,
    ) -> None:
        if nn_goal != sym_goal:
            self.events.append(
                DisagreementEvent(
                    seed=seed,
                    step=step,
                    map_id=map_id,
                    pos=pos,
                    nn_goal=nn_goal,
                    sym_goal=sym_goal,
                )
            )

    def finalize_episode(self, seed: int, outcome: str) -> None:
        for ev in self.events:
            if ev.seed == seed and ev.outcome == "pending":
                ev.outcome = outcome

    def nn_won_disagreements(self) -> list[DisagreementEvent]:
        return [ev for ev in self.events if ev.outcome == "WON"]

    def export_nn_won_disagreements(self, path: str | Path) -> int:
        rows = [asdict(ev) for ev in self.nn_won_disagreements()]
        Path(path).write_text(json.dumps(rows, indent=2), encoding="utf-8")
        return len(rows)


def train_macro_bc(
    samples: list[MacroSample],
    train_seeds: list[int] | tuple[int, ...],
    *,
    epochs: int = 20,
    batch_size: int = 256,
    lr: float = 1e-3,
    val_fraction: float = 0.15,
    value_coef: float = 0.25,
    device: str | None = None,
) -> tuple[MacroCriticNet, dict[str, Any]]:
    """Train MacroCriticNet via masked cross-entropy + milestone value MSE."""
    validate_train_seeds(train_seeds)
    if not samples:
        raise ValueError("Cannot train MacroCriticNet on empty samples list.")
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    feats = torch.tensor([s.features for s in samples], dtype=torch.float32)
    masks = torch.tensor([s.legal_mask for s in samples], dtype=torch.bool)
    goals = torch.tensor([s.goal_idx for s in samples], dtype=torch.long)
    rets = torch.tensor([s.milestone_return for s in samples], dtype=torch.float32)

    n_total = len(samples)
    n_val = max(1, int(n_total * val_fraction)) if n_total >= 5 else 0
    n_train = n_total - n_val

    perm = torch.randperm(n_total, generator=torch.Generator().manual_seed(42))
    train_idx = perm[:n_train]
    val_idx = perm[n_train:] if n_val > 0 else perm[:n_train]

    model = MacroCriticNet().to(device)
    param_count = model.count_parameters()
    if param_count > MAX_MACRO_PARAMS:
        raise RuntimeError(f"MacroCriticNet exceeds {MAX_MACRO_PARAMS} params: {param_count}")

    with torch.no_grad():
        mean = feats[train_idx].mean(dim=0)
        std = feats[train_idx].std(dim=0).clamp(min=1e-3)
        model.feat_mean.copy_(mean.to(device))
        model.feat_std.copy_(std.to(device))

    loader = DataLoader(
        TensorDataset(feats[train_idx], masks[train_idx], goals[train_idx], rets[train_idx]),
        batch_size=min(batch_size, max(1, n_train)),
        shuffle=True,
    )
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-2)
    ce_loss = nn.CrossEntropyLoss()

    model.train()
    for _ in range(epochs):
        for b_f, b_m, b_g, b_r in loader:
            b_f, b_m, b_g, b_r = b_f.to(device), b_m.to(device), b_g.to(device), b_r.to(device)
            opt.zero_grad()
            logits, vals = model(b_f, b_m)
            loss = ce_loss(logits, b_g) + value_coef * nn.functional.mse_loss(vals, b_r)
            loss.backward()
            opt.step()

    model.eval()
    with torch.no_grad():
        v_logits, v_vals = model(feats[val_idx].to(device), masks[val_idx].to(device))
        val_acc = float((v_logits.argmax(dim=-1) == goals[val_idx].to(device)).float().mean().item())
        val_mse = float(nn.functional.mse_loss(v_vals, rets[val_idx].to(device)).item())

    meta = {
        "git_sha": current_git_sha(),
        "train_seeds": list(train_seeds),
        "param_count": param_count,
        "transitions": n_total,
        "val_acc": val_acc,
        "val_mse": val_mse,
        "device": device,
    }
    return model, meta


def save_macro_checkpoint(
    path: str | Path,
    model: MacroCriticNet,
    meta: dict[str, Any],
) -> None:
    """Save MacroCriticNet weights and provenance metadata."""
    torch.save({"meta": dict(meta), "state_dict": model.state_dict()}, Path(path))


def load_macro_checkpoint(
    path: str | Path,
    *,
    device: str = "cpu",
) -> tuple[MacroCriticNet, dict[str, Any]]:
    """Load MacroCriticNet checkpoint and metadata."""
    ckpt = torch.load(Path(path), map_location=device, weights_only=False)
    model = MacroCriticNet().to(device)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    return model, dict(ckpt["meta"])
