"""Combat package for py-exodus (Tactical Combat Arena & Resolvers)."""
from py_exodus.combat.arena import Action, ActionResult, ActionType, CombatArena, CombatMonster
from py_exodus.combat.resolver import (
    AttackResolution,
    AttackResult,
    AttackVector,
    calculate_monster_damage,
    calculate_player_damage,
    resolve_monster_attack,
    resolve_player_attack,
    roll_hit,
    trace_projectile_path,
)

__all__ = [
    "Action",
    "ActionResult",
    "ActionType",
    "AttackResolution",
    "AttackResult",
    "AttackVector",
    "CombatArena",
    "CombatMonster",
    "calculate_monster_damage",
    "calculate_player_damage",
    "resolve_monster_attack",
    "resolve_player_attack",
    "roll_hit",
    "trace_projectile_path",
]
