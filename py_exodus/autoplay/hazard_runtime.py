"""Runtime wrapper for the hazard critic (autoplay strategy layer).

Loads ``nn/checkpoints/hazard_critic.pt`` when present and serves cached
risk maps (per map + party power bucket) that the controller injects into
A* edge costs. Enabled only when both a checkpoint and the env flag exist
— default-off keeps autoplay behavior byte-identical when the strategy
layer isn't wanted.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_HAZARD_CHECKPOINT = (
    Path(__file__).resolve().parent.parent / "nn" / "checkpoints" / "hazard_critic.pt"
)

#: Region half-width for the cached local risk map.
RISK_REGION = 24
#: Party-state bucket granularity for cache keys.
_BUCKET = 5


def hazard_alpha_from_env() -> float:
    try:
        return float(os.environ.get("PY_EXODUS_HAZARD_ALPHA", "0") or 0)
    except ValueError:
        return 0.0


class HazardRuntime:
    """Cached risk-map provider; inert without checkpoint + env flag."""

    def __init__(
        self,
        checkpoint: Path | str | None = None,
        alpha: float | None = None,
        device: str | None = None,
    ) -> None:
        self.alpha = hazard_alpha_from_env() if alpha is None else alpha
        self.checkpoint = Path(checkpoint) if checkpoint else DEFAULT_HAZARD_CHECKPOINT
        self.device = device or "cpu"
        self.model: Any = None
        self.meta: dict[str, Any] = {}
        self._cache: dict[tuple[int, int, int, int], dict[tuple[int, int], float]] = {}
        self._load()

    def _load(self) -> None:
        if self.alpha <= 0.0 or not self.checkpoint.exists():
            logger.info(
                "Hazard critic disabled (alpha=%s, ckpt=%s)",
                self.alpha, self.checkpoint,
            )
            return
        try:
            import torch

            from py_exodus.nn.hazard_critic import load_hazard_checkpoint

            self.model, self.meta = load_hazard_checkpoint(
                self.checkpoint, device=self.device
            )
            logger.info(
                "Hazard critic active (alpha=%.2f, %s, precision=%.2f recall=%.2f)",
                self.alpha, self.checkpoint.name,
                self.meta.get("precision", -1), self.meta.get("recall", -1),
            )
        except Exception as exc:
            self.alpha = 0.0
            self.model = None
            logger.warning("Hazard critic failed to load: %s", exc)

    @property
    def active(self) -> bool:
        return self.model is not None and self.alpha > 0.0

    def _state_bucket(self, party) -> tuple[int, int]:
        living = [m for m in party.members if not m.is_dead()]
        min_hp = min((m.hp / max(1, m.max_hp) for m in living), default=1.0)
        min_lvl = min((m.level for m in living), default=0)
        mark_force = sum(1 for m in party.members if m.marks[3] > 0)
        return (min_lvl // _BUCKET, int(min_hp * _BUCKET) + mark_force * 1000)

    def risk_map(self, party, screen) -> dict[tuple[int, int], float] | None:
        if not self.active:
            return None
        gmap = screen.game_map
        px, py = party.x, party.y
        key = (getattr(gmap, "id", 0), *self._state_bucket(party), (px // RISK_REGION, py // RISK_REGION))
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        import torch

        from py_exodus.nn.hazard_critic import build_risk_map

        risks = build_risk_map(
            self.model, party, screen, device=self.device, region=RISK_REGION
        )
        self._cache.clear()  # keep at most one map live per regime
        self._cache[key] = risks
        return risks

    def hazard_costs(self, party, screen) -> dict[tuple[int, int], float] | None:
        """Scaled costs ready to hand to find_2d_step."""
        risks = self.risk_map(party, screen)
        if risks is None:
            return None
        return {
            pos: self.alpha * risk
            for pos, risk in risks.items()
            if risk > 0.0
        }
