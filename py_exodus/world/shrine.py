"""Ambrosia's shrines, the LairWare way (UltimaMain.c:1461-1484, UltimaMisc.c
Shrine()): no separate screen. Stand on a shrine and Enter: "Who enters?",
then "Offering*100-" a digit 0-9; the stat is set by the shrine's x position
(x & 3: Strength, Dexterity, Intelligence, Wisdom)."""
from __future__ import annotations

SHRINE_STATS: tuple[str, ...] = ("strength", "dexterity", "intelligence", "wisdom")
_RACE_CAP = {"strength": "max_str", "dexterity": "max_dex",
             "intelligence": "max_int", "wisdom": "max_wis"}

MSG_WHO = "Enter shrine!"
PROMPT_WHO = "Who enters?-"
PROMPT_OFFER = "Offering*100-"
MSG_INCAP = "Incapacitated!"
MSG_BEGONE = "Then be off!"
MSG_CHEAT = "YOU CAN'T CHEAT THE GODS!"
MSG_SHAZAM = "SHAZAM!"


def shrine_stat(x: int) -> str:
    """LairWare ``shtype = xpos & 0x03``."""
    return SHRINE_STATS[x & 3]


def welcome(stat: str) -> str:
    return f"Welcome to the Shrine of {stat.capitalize()}"


def offer(party, member, stat: str, amount: int) -> str:
    """Take ``amount`` hundred gold from the member and raise ``stat`` by
    ``amount``: capped at 99, then at the race's maximum (UltimaMisc.c:
    1071-1093; the full offering is charged even when the cap grants less).
    LW lifts the race cap once Exodus falls (``Party[16]``, :1091); the game
    ends there now (user ruling 2026-11-25), so the cap always holds.
    Returns the message to show."""
    if amount <= 0:
        return MSG_BEGONE
    char = getattr(member, "player", member)
    cost = amount * 100
    if getattr(char, "gold", 0) < cost:
        return MSG_CHEAT
    char.adjust_gold(-cost)
    value = min(99, getattr(char, stat) + amount)
    cap = getattr(char.race, _RACE_CAP[stat])
    value = min(value, cap)
    setattr(char, stat, value)
    return MSG_SHAZAM
