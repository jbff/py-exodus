"""Neural network hybrid policy modules for py-exodus (Phase 1+ on neural-net branch)."""
from __future__ import annotations

__all__ = [
    "COMBAT_CONTEXT_DIM",
    "COMBAT_GRID_CHANNELS",
    "NUM_COMBAT_ACTIONS",
    "action_to_index",
    "encode_combat_state",
    "index_to_action",
    "legal_action_mask",
]

from py_exodus.nn.combat_env import (
    COMBAT_CONTEXT_DIM,
    COMBAT_GRID_CHANNELS,
    NUM_COMBAT_ACTIONS,
    action_to_index,
    encode_combat_state,
    index_to_action,
    legal_action_mask,
)
