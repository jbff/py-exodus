"""Economy critic: supervised gold-accumulation-rate by grind context.

The failure mode this attacks (2026-11-20 live runs + 48-seed rollouts):
wipeless parties camp in GRIND_AND_LEVEL forever with 73-500g — they never
reach Ambrosia because the grind loop chases the NEAREST prey rather than
the most gold-productive one, while food purchases and cure costs drain at
a fixed rate. This critic learns E[gold delta per step] for a context
(party power, hp state, transport, region, nearby creature mix) from the
same rollout logs the hazard critic uses, so the grind loop can price
candidate prey: gank what actually pays at your power level.

Targets derived from consecutive rows: gold delta between state changes,
normalized per recorded step (rows are turn-deduplicated, so the delta is
already per-elapsed-steps).
"""
from __future__ import annotations

import gzip
import json
import logging
from pathlib import Path
from typing import Any

import torch
from torch import nn

from py_exodus.nn.hazard_critic import FEATURE_DIM, build_features, _git_sha

logger = logging.getLogger(__name__)

#: Creature tiles attributable as combat opponents (creatures.xml battle set).
_KNOWN_THREATS = frozenset(
    ("orc", "skeleton", "thief", "giant", "daemon", "fighter", "wizard",
     "pincher", "dragon", "balron", "pirate", "serpent", "squid")
)


def build_economy_dataset(
    rollout_dir: Path | str,
    *,
    max_rate: float = 0.5,
) -> tuple[torch.Tensor, torch.Tensor, int]:
    """(features, gold-rate targets, row count) from recorded rollouts.

    ``max_rate`` clamps outliers so one lucky chest does not dominate the
    MSE; rates above it are clipped and flagged.
    """
    rollouts = sorted(Path(rollout_dir).glob("rollout_*.jsonl.gz")) + sorted(
        Path(rollout_dir).glob("rollout_*.jsonl")
    )
    X, y = [], []
    for path in rollouts:
        opener = gzip.open if path.suffix == ".gz" else open
        rows = [
            json.loads(line)
            for line in opener(path, "rt").read().splitlines()
            if line.strip()
        ]
        open_combat = None
        for r in rows:
            if r.get("t") == "combat_start":
                open_combat = r
            elif r.get("t") == "combat_end" and open_combat is not None:
                delta = float(r.get("gold_delta", 0))
                if delta <= 0:
                    open_combat = None  # lost fights teach "avoid", not "yield"
                    continue
                steps = 1
                # Attribute yield to the ENGAGED creature mix.
                row = dict(open_combat)
                row["nearby"] = {
                    t: 0 for t in (row.get("creatures") or ())
                    if t in _KNOWN_THREATS
                }
                steps = max(1, int(r.get("step", 0)) - int(open_combat.get("step", 0)))
                rate = min(delta / max(1, steps), max_rate)
                X.append(build_features(row))
                y.append(rate)
                open_combat = None
    if not X:
        raise RuntimeError(f"no recorded states under {rollout_dir}")
    return (
        torch.tensor(X, dtype=torch.float32),
        torch.tensor(y, dtype=torch.float32),
        len(y),
    )


class EconomyCriticNet(nn.Module):
    def __init__(self, in_dim: int = FEATURE_DIM, hidden: int = 96) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
            nn.Linear(hidden, 1),
        )
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)

    def count_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters())

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)

    def rate(self, x: torch.Tensor) -> torch.Tensor:
        return torch.relu(self(x)).squeeze(-1)


def train_economy_critic(
    rollout_dir: Path | str,
    *,
    epochs: int = 60,
    device: str | None = None,
) -> tuple[EconomyCriticNet, dict[str, Any]]:
    X, y, n = build_economy_dataset(rollout_dir)
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    model = EconomyCriticNet().to(device)
    criterion = nn.MSELoss()
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)

    perm = torch.randperm(n, generator=torch.Generator().manual_seed(11))
    n_val = max(1, n // 10)
    val_idx = perm[:n_val]
    train_idx = perm[n_val:]

    model.train()
    for _ in range(epochs):
        for start in range(0, len(train_idx), 512):
            sl = slice(start, start + 512)
            xb = X[train_idx[sl]].to(device)
            yb = y[train_idx[sl]].to(device)
            opt.zero_grad()
            pred = model(xb).squeeze(-1)
            loss = criterion(pred, yb)
            loss.backward()
            opt.step()

    model.eval()
    with torch.no_grad():
        pred_v = model(X[val_idx].to(device)).squeeze(-1).cpu()
        yv = y[val_idx]
        mae = float(torch.mean(torch.abs(pred_v - yv)))
        # Spearman-ish: does higher predicted rate mean higher realized rate?
        order_p = torch.argsort(pred_v)
        order_y = torch.argsort(yv)
        ranks = torch.empty_like(yv)
        ranks[order_y] = torch.arange(len(yv), dtype=torch.float32)
        rank_p = torch.empty_like(yv)
        rank_p[order_p] = torch.arange(len(yv), dtype=torch.float32)
        corr = float(torch.corrcoef(torch.stack([rank_p, ranks]))[0, 1])
    meta = {
        "git_sha": _git_sha(),
        "rows": n,
        "mae_gold_per_step": round(mae, 5),
        "rank_corr": round(corr, 4),
        "params": model.count_parameters(),
        "device": device,
    }
    return model, meta


def save_economy_checkpoint(path: Path | str, model: EconomyCriticNet, meta: dict[str, Any]) -> None:
    torch.save({"meta": meta, "state_dict": model.state_dict()}, Path(path))


def load_economy_checkpoint(
    path: Path | str, *, device: str = "cpu"
) -> tuple[EconomyCriticNet, dict[str, Any]]:
    ckpt = torch.load(Path(path), map_location=device, weights_only=False)
    model = EconomyCriticNet().to(device)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    return model, dict(ckpt["meta"])


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rollout-dir", default="py_exodus/nn/data/rollouts")
    ap.add_argument("--out", default="py_exodus/nn/checkpoints/economy_critic.pt")
    ap.add_argument("--epochs", type=int, default=60)
    args = ap.parse_args()
    model, meta = train_economy_critic(args.rollout_dir, epochs=args.epochs)
    save_economy_checkpoint(args.out, model, meta)
    print("trained:", {k: v for k, v in meta.items()})
