"""Hazard critic: supervised P(near-death/wipe soon | position, party, threats).

The strategy layer the user asked for (2026-11-20): the symbolic controller
keeps doing WHAT/WHERE correctly; this critic prices WHERE in its pathing.
Trained on symbolic rollout logs (rollout_recorder): each recorded state
row is labeled positive when the party reaches a near-death state (min hp
fraction < 0.25) or wipes within the following ``horizon`` recorded rows.

Integration: risk values become extra A* edge costs in find_2d_step via
the controller, so the planner detours around tiles/regions where the
teacher historically walked into trouble at the party's current power
level — without replacing any pathing logic.
"""
from __future__ import annotations

import gzip
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

import torch
from torch import nn

logger = logging.getLogger(__name__)

#: Near-death threshold for positive labels.
NEAR_DEATH_HP_FRAC = 0.25
#: How many subsequent recorded rows count as "soon".
DEFAULT_HORIZON = 25

_THREAT_TILES = (
    "serpent", "pirate", "squid", "thief", "skeleton", "orc", "giant",
    "daemon", "fighter", "wizard", "pincher", "dragon", "balron",
)
#: Goals the critic sees as one-hot categories.
_GOAL_KEYS = (
    "GRIND_AND_LEVEL", "OUTFIT_BRITAIN", "BUY_FOOD", "DIG_EXOTICS",
    "GET_MARK_KINGS", "CAPTURE_SHIP", "SAIL_WHIRLPOOL", "AMBROSIA_CARDS_SHRINES",
    "EXIT_AMBROSIA", "RESURRECT_DEAD", "CURE_POISON", "DEATH_GULCH_RAID",
)

FEATURE_DIM = 48


def build_features(row: dict[str, Any]) -> list[float]:
    """Map a recorded state row to the critic feature vector."""
    living = max(1, row.get("living", 4))
    marks_any = [max((m[i] for m in row.get("marks", [])), default=0) for i in range(4)]
    nearby = row.get("nearby", {}) or {}
    # Threat pressure: for each tracked tile, 1.0 / (1 + min distance).
    threat = [0.0] * len(_THREAT_TILES)
    for tile, dist in nearby.items():
        key = str(tile).lower()
        if key in _THREAT_TILES:
            threat[_THREAT_TILES.index(key)] = 1.0 / (1.0 + float(dist))
    min_threat_dist = min(nearby.values(), default=99)
    transport = row.get("transport", "foot")
    goal = str(row.get("goal", "")).replace("Goal.", "")
    feats = [
        float(row.get("min_hp_frac", 1.0)),
        float(sum(row.get("levels", [1, 1, 1, 1])) / (4.0 * 25.0)),
        float(max(row.get("levels", [1, 1, 1, 1])) / 25.0),
        float(living) / 4.0,
        min(1.0, float(row.get("gold", 0)) / 4500.0),
        min(1.0, float(row.get("food", 300)) / 900.0),
        *[float(marks_any[i]) for i in range(4)],
        1.0 if transport == "foot" else 0.0,
        1.0 if transport == "ship" else 0.0,
        (float(row.get("hull") or 0.0) / 50.0) if row.get("hull") is not None else 0.0,
        (float(row["x"]) % 64.0) / 64.0,
        (float(row["y"]) % 64.0) / 64.0,
        1.0 if int(row.get("map", 0)) == 0 else 0.0,
        1.0 if int(row.get("map", 0)) == 13 else 0.0,
        1.0 if int(row.get("map", 0)) in (14, 15, 16, 17, 18, 19, 20) else 0.0,
        float(len(nearby)) / 6.0,
        1.0 / (1.0 + float(min_threat_dist)),
        *[float(g == goal) for g in _GOAL_KEYS],
    ]
    out = feats + threat
    # Pad/trim to FEATURE_DIM for stable tensor shape as the schema evolves.
    if len(out) < FEATURE_DIM:
        out = out + [0.0] * (FEATURE_DIM - len(out))
    return out[:FEATURE_DIM]


def build_dataset(
    rollout_dir: Path | str,
    *,
    horizon: int = DEFAULT_HORIZON,
) -> tuple[torch.Tensor, torch.Tensor, int]:
    """Rows + labels + positive count from recorded rollouts."""
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
        end_rows = [i for i, r in enumerate(rows) if r.get("t") == "end"]
        if end_rows:
            rows = rows[: end_rows[0]]
        states = [r for r in rows if r.get("t") == "s"]
        n = len(states)
        for i, r in enumerate(states):
            label = 0
            for j in range(i + 1, min(n, i + horizon + 1)):
                nxt = states[j]
                if nxt.get("min_hp_frac", 1.0) < NEAR_DEATH_HP_FRAC:
                    label = 1
                    break
            X.append(build_features(r))
            y.append(label)
    if not X:
        raise RuntimeError(f"no recorded states under {rollout_dir}")
    return torch.tensor(X, dtype=torch.float32), torch.tensor(y, dtype=torch.float32), int(sum(y))


class HazardCriticNet(nn.Module):
    """Small MLP over the hazard features (~30k params)."""

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

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)

    def count_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters())

    def risk(self, x: torch.Tensor) -> torch.Tensor:
        """P(near-death soon) in [0, 1]."""
        return torch.sigmoid(self(x)).squeeze(-1)


def train_hazard_critic(
    rollout_dir: Path | str,
    *,
    epochs: int = 40,
    horizon: int = DEFAULT_HORIZON,
    device: str | None = None,
    pos_weight_boost: float = 8.0,
) -> tuple[HazardCriticNet, dict[str, Any]]:
    X, y, positives = build_dataset(rollout_dir, horizon=horizon)
    n = len(y)
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    model = HazardCriticNet().to(device)
    pos_weight = torch.tensor(
        [max(1.0, pos_weight_boost * (n - positives) / max(1, positives))],
        device=device,
    )
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)

    perm = torch.randperm(n, generator=torch.Generator().manual_seed(7))
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
            logits = model(xb).squeeze(-1)
            loss = criterion(logits, yb)
            loss.backward()
            opt.step()

    model.eval()
    import math

    with torch.no_grad():
        logits_v = model(X[val_idx].to(device)).squeeze(-1).cpu()
        yv = y[val_idx]
        preds = (torch.sigmoid(logits_v) > 0.5).float()
        prec = preds.sum() / max(1.0, preds.sum())
        # Precision on positives matters more than raw accuracy under skew.
        tp = ((preds == 1.0) & (yv == 1.0)).sum()
        fp = ((preds == 1.0) & (yv == 0.0)).sum()
        fn = ((preds == 0.0) & (yv == 1.0)).sum()
        precision = tp / max(1.0, tp + fp)
        recall = tp / max(1.0, tp + fn)
    meta = {
        "git_sha": _git_sha(),
        "horizon": horizon,
        "rows": n,
        "positives": positives,
        "precision": float(precision),
        "recall": float(recall),
        "params": model.count_parameters(),
        "device": device,
    }
    return model, meta


def _git_sha() -> str:
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def save_hazard_checkpoint(path: Path | str, model: HazardCriticNet, meta: dict[str, Any]) -> None:
    torch.save({"meta": meta, "state_dict": model.state_dict()}, Path(path))


def load_hazard_checkpoint(
    path: Path | str, *, device: str = "cpu"
) -> tuple[HazardCriticNet, dict[str, Any]]:
    ckpt = torch.load(Path(path), map_location=device, weights_only=False)
    model = HazardCriticNet().to(device)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    return model, dict(ckpt["meta"])


def build_risk_map(
    model: HazardCriticNet,
    party,
    screen,
    *,
    device: str = "cpu",
    region: int = 24,
) -> dict[tuple[int, int], float]:
    """Risk value for every tile in the party's local region (cacheable)."""
    from py_exodus.nn.rollout_recorder import _party_snapshot, _nearby_threats

    party_obj = party
    px, py = party_obj.x, party_obj.y
    gmap = screen.game_map
    risks: dict[tuple[int, int], float] = {}
    base_row = {
        "map": getattr(gmap, "id", 0),
        "goal": "",
        "living": sum(1 for m in party_obj.members if not m.is_dead()),
        **_party_snapshot(party_obj, screen),
    }
    for dy in range(-region // 2, region // 2 + 1):
        for dx in range(-region // 2, region // 2 + 1):
            x = (px + dx) % gmap.width
            y = (py + dy) % gmap.height
            row = dict(base_row)
            row["x"], row["y"] = x, y
            row["nearby"] = _nearby_threats(screen).get("nearby", {})
            feats = torch.tensor([build_features(row)], dtype=torch.float32, device=device)
            with torch.no_grad():
                risks[(x, y)] = float(model.risk(feats)[0].item())
    return risks


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rollout-dir", default="py_exodus/nn/data/rollouts")
    ap.add_argument("--out", default="py_exodus/nn/checkpoints/hazard_critic.pt")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--horizon", type=int, default=DEFAULT_HORIZON)
    args = ap.parse_args()

    model, meta = train_hazard_critic(args.rollout_dir, epochs=args.epochs, horizon=args.horizon)
    save_hazard_checkpoint(args.out, model, meta)
    print("trained:", {k: v for k, v in meta.items()})
