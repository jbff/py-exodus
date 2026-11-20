"""Runtime for the economy critic: yield-scored prey selection.

Inert unless a trained checkpoint exists AND PY_EXODUS_ECONOMY_GUIDE is
set — when active, the GRIND prey chase prefers creature tiles with the
best predicted gold yield at the party's power level ("gank what pays")
over chasing whatever is nearest.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_ECONOMY_CHECKPOINT = (
    Path(__file__).resolve().parent.parent / "nn" / "checkpoints" / "economy_critic.pt"
)


def economy_guide_enabled() -> bool:
    raw = os.environ.get("PY_EXODUS_ECONOMY_GUIDE", "")
    return raw.strip().lower() in ("1", "true", "yes", "on")


class EconomyRuntime:
    def __init__(
        self,
        checkpoint: Path | str | None = None,
        device: str | None = None,
        enabled: bool | None = None,
    ) -> None:
        self.checkpoint = Path(checkpoint) if checkpoint else DEFAULT_ECONOMY_CHECKPOINT
        self.device = device or "cpu"
        self.enabled = economy_guide_enabled() if enabled is None else enabled
        self.model: Any = None
        self.meta: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not self.enabled:
            logger.info("Economy guide disabled (no PY_EXODUS_ECONOMY_GUIDE)")
            return
        if not self.checkpoint.exists():
            logger.info("Economy critic checkpoint missing: %s", self.checkpoint)
            return
        try:
            import torch

            from py_exodus.nn.economy_critic import load_economy_checkpoint

            self.model, self.meta = load_economy_checkpoint(
                self.checkpoint, device=self.device
            )
            logger.info(
                "Economy critic active (%s, rank_corr=%.2f)",
                self.checkpoint.name, self.meta.get("rank_corr", -1),
            )
        except Exception as exc:
            self.enabled = False
            self.model = None
            logger.warning("Economy critic failed to load: %s", exc)

    @property
    def active(self) -> bool:
        return self.model is not None and self.enabled

    def score_prey(self, party, screen, tile_name: str, cx: int, cy: int) -> float:
        """Predicted gold/step if the party engages this creature now."""
        import torch

        from py_exodus.nn.hazard_critic import build_features
        from py_exodus.nn.rollout_recorder import _party_snapshot, _nearby_threats

        row = {
            "t": "s",
            "map": getattr(getattr(screen, "game_map", None), "id", getattr(party, "map_id", 0)),
            "x": cx,
            "y": cy,
            "goal": "GRIND_AND_LEVEL",
            "nearby": {str(tile_name).lower(): 0},
            **_party_snapshot(party, screen),
        }
        # _nearby_threats(screen) adds other ambient threats at distance —
        # intentionally overlaid so the critic sees the full context.
        nearby = dict(row["nearby"])
        nearby.update(_nearby_threats(screen).get("nearby", {}))
        row["nearby"] = nearby
        feats = torch.tensor([build_features(row)], dtype=torch.float32, device=self.device)
        with torch.no_grad():
            return float(self.model.rate(feats)[0].item())

    def select_prey(
        self,
        party,
        screen,
        candidates: list[tuple[str, int, int]],
        *,
        top_fraction: float = 0.5,
    ) -> set[tuple[int, int]] | None:
        """Restrict candidate prey tiles to the best-yielding fraction.

        ``candidates``: (tile_name, x, y). Returns the preferred subset, or
        None when inert (caller falls back to all candidates).
        """
        if not self.active or not candidates:
            return None
        scored = sorted(
            ((self.score_prey(party, screen, t, x, y), x, y) for t, x, y in candidates),
            reverse=True,
        )
        keep = max(1, int(len(scored) * top_fraction))
        return {(x, y) for _, x, y in scored[:keep]}
