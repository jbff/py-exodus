"""Aura effects carried by the party (Java ``objects/Aura.java`` and the
``AuraType`` enum at ``exodus/Constants.java:878-886``).

The aura is a single typed effect with a turn duration. N (negate time) sets
QUICKNESS for 10 (LairWare NegateTime, ``gTimeNegate = 10``); ``pass_turn``
counts it down where LairWare does: in FinishAll on turns the monsters would
move (10 turns on foot, about 20 mounted) and once a combat round. Meals,
moons, poison and healing carry on under it (ledger T-13). This module only
provides the carrier.
"""
from __future__ import annotations

from enum import Enum, auto


class AuraType(Enum):
    """Java ``Constants.AuraType`` (Constants.java:878-886)."""

    NONE = auto()
    HORN = auto()
    JINX = auto()
    NEGATE = auto()
    PROTECTION = auto()
    QUICKNESS = auto()


class Aura:
    """One typed effect with a counted-down duration (Java Aura.java)."""

    def __init__(self) -> None:
        self._type: AuraType = AuraType.NONE
        self._duration: int = 0

    def set(self, aura_type: AuraType, duration: int) -> None:
        """Java ``Aura.set(AuraType, int)``."""
        self._type = aura_type
        self._duration = duration

    def get_duration(self) -> int:
        return self._duration

    def set_duration(self, duration: int) -> None:
        self._duration = duration

    def get_type(self) -> AuraType:
        return self._type

    def set_type(self, aura_type: AuraType) -> None:
        self._type = aura_type

    def is_active(self) -> bool:
        return self._duration > 0

    def pass_turn(self) -> None:
        """Java ``Aura.passTurn`` — decrement; the type resets to NONE at 0."""
        if self._duration > 0:
            self._duration -= 1
            if self._duration == 0:
                self._type = AuraType.NONE
