"""Runtime NN combat policy for AutoPlayController (neural-net branch).

Loads the shipped CombatPolicyNet checkpoint and drives combat turns
directly on the arena, mirroring the offline evaluator in
``py_exodus.nn.hybrid_eval``.

On this branch there is NO symbolic fallback: if you ask for NN combat
and the net cannot load, construction raises. If inference fails, the
error propagates. Either the NN plays combat or the run fails loudly.

Contract for :meth:`CombatNNPolicy.step_combat`:

* ``None`` — a turn was executed directly on the arena; nothing to emit.
* ``int``  — a key the controller should emit (e.g. ``K_RETURN``).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pygame

if TYPE_CHECKING:
    from py_exodus.state_machine import StateMachine

logger = logging.getLogger(__name__)

#: Tracked checkpoint location inside the repo.
DEFAULT_CHECKPOINT = (
    Path(__file__).resolve().parent.parent / "nn" / "checkpoints" / "combat_ppo.pt"
)


def _torch():
    """Import torch (required on this branch when NN combat is enabled)."""
    import torch

    return torch


def _cuda_available() -> bool:
    try:
        return bool(_torch().cuda.is_available())
    except Exception:
        return False


def resolve_device(preference: str = "auto") -> str:
    """Pick the torch device; CUDA when available, with CPU fallback."""
    if preference == "auto":
        return "cuda" if _cuda_available() else "cpu"
    if preference == "cuda":
        if _cuda_available():
            return "cuda"
        logger.warning("nn-device cuda requested but CUDA is unavailable; using CPU")
        return "cpu"
    return "cpu"


class CombatNNPolicy:
    """Drives CombatArena turns through the trained CombatPolicyNet.

    Loads once at construction and stays resident for the controller's
    lifetime — the game enters combat frequently, so the policy must never
    reload per encounter.
    """

    def __init__(
        self,
        checkpoint: Path | str | None = None,
        device: str = "auto",
    ) -> None:
        self.checkpoint = Path(checkpoint) if checkpoint else DEFAULT_CHECKPOINT
        self.preference = device
        self.device = "cpu"
        self.model: Any = None
        self.meta: dict[str, Any] = {}
        self._load()

    # -- lifecycle ---------------------------------------------------------

    def _load(self) -> None:
        self.device = resolve_device(self.preference)
        if not self.checkpoint.exists():
            raise RuntimeError(
                f"NN combat policy checkpoint missing: {self.checkpoint}"
            )
        from py_exodus.nn.combat_bc import load_combat_checkpoint

        try:
            self.model, self.meta = load_combat_checkpoint(
                self.checkpoint, device=self.device
            )
        except Exception as exc:
            if self.device == "cuda":
                # CUDA init can fail despite availability checks; a CPU
                # retry still runs the NN, which is the contract here.
                self.model, self.meta = load_combat_checkpoint(
                    self.checkpoint, device="cpu"
                )
                self.device = "cpu"
                logger.warning("NN combat CUDA load failed; using CPU: %s", exc)
            else:
                raise RuntimeError(
                    f"NN combat policy failed to load from {self.checkpoint}: {exc}"
                ) from exc
        logger.info(
            "NN combat policy active on %s (%s)", self.device, self.checkpoint.name
        )

    @property
    def available(self) -> bool:
        return self.model is not None

    # -- combat steps ------------------------------------------------------

    def step_combat(self, state_machine: StateMachine, screen: Any) -> int | None:
        """Act with the net on ``screen``; return a key to emit or None.

        Errors propagate — on this branch a failing NN inference must not
        silently degrade to the symbolic policy.
        """
        return self._run_turn(screen)

    def _run_turn(self, screen: Any) -> int | None:
        arena = screen.arena
        if arena.is_finished:
            return pygame.K_RETURN
        m_idx = arena.active_party_member_idx
        from py_exodus.nn.combat_env import (
            encode_combat_state,
            index_to_action,
            legal_action_mask,
        )

        asset_mgr = screen.asset_mgr
        grid, ctx = encode_combat_state(arena, m_idx, screen=screen, asset_mgr=asset_mgr)
        mask = legal_action_mask(arena, m_idx, asset_mgr=asset_mgr)
        torch = _torch()
        with torch.no_grad():
            logits, _ = self.model(
                torch.tensor([grid], dtype=torch.float32, device=self.device),
                torch.tensor([ctx], dtype=torch.float32, device=self.device),
                torch.tensor([mask], dtype=torch.bool, device=self.device),
            )
            action = index_to_action(
                int(logits[0].argmax(dim=-1).item()),
                arena,
                m_idx,
                asset_mgr=asset_mgr,
            )
        arena.execute_turn(action)
        return None
