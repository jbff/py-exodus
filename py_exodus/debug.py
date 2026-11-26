"""GBC debug/cheat harness (D1); runtime-only state.

GBC truth: ``u3/cheat.c:414-825`` — ``docheat`` presents an 8-item menu
(MUSIC track picker first), each remaining item toggles a cheat byte
(``cheat_xray`` &c. via the ``+= 0x80`` flip), and the last item runs
``domaxall`` (``cheat.c:441-479``). The menu description strings come from
``cheatdescdat`` (``cheat.c:77-102``).

MUSIC jukebox: OMITTED from the menu — there is no track-picker widget in
the py port and no per-track selection path (music routing is a D5
deferral), so the GBC "[TEST] MUSIC" item has nothing to drive.

Runtime-only guarantee: nothing in this module is referenced by any
``to_dict()``/save serializer — the cheat state dies with the process,
exactly like GBC's ``cheat_*`` bytes never entering the SRAM image. Tests
pin that contract (``tests/test_debug_menu.py::TestCheatNeverSaved``).

USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): debug cheat harness
(GBC cheat.c:414-825 docheat/domaxall).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Master debug switch, set from the ``--debug`` CLI flag (``__main__.py``).
#: Only gates the MENU — the effect sites check ``CHEATS`` directly, so a
#: toggle keeps working once set (and all toggles default False in a fresh
#: process, the same "off unless asked for" posture GBC ships with).
DEBUG_MODE: bool = False


@dataclass
class CheatState:
    """The six GBC cheat toggles (``cheat.c:40-46`` extern bytes), and the
    port's own ``free_peer`` (user request 2026-11-26).

    Deliberately NOT frozen: effect sites and tests mutates the singleton's
    fields in place (GBC flips its ``cheat_*`` bytes the same way); the
    test fixture restores the saved field values in teardown instead of
    re-binding the module attribute, so held references stay valid.
    """

    xray: bool = False  #: SEE THROUGH ANY TILE
    nofight: bool = False  #: AUTO WIN EVERY BATTLE (no random battles)
    nohurt: bool = False  #: HP NEVER DECREASES
    noblock: bool = False  #: WALK THROUGH ANY TILE
    full_mp: bool = False  #: MP NEVER DECREASES
    no_class: bool = False  #: ANY CHAR CAN CAST ANY SPELL
    #: P SHOWS THE MAP ANYWHERE, NO GEM: surface, town and dungeon.  Not a
    #: GBC cheat; it replaces the dungeon's old free map overlay.
    free_peer: bool = False


#: The single instance the effect sites read; tests mutate it directly and
#: reset in the fixture teardown.
CHEATS = CheatState()


def set_debug(enabled: bool) -> None:
    """Set the master debug switch from the parsed ``--debug`` flag."""
    global DEBUG_MODE
    DEBUG_MODE = bool(enabled)


# GBC labels (``cheatmenudat``, cheat.c:65-77, MUSIC dropped) and decoded
# descriptions (``cheatdescdat``, cheat.c:77-102): 3 rows of 12 glyphs each.
_MENU_ITEMS: list[tuple[str, str, str]] = [
    ("XRAY", "SEE THROUGH ANY TILE", "xray"),
    ("NOFIGHT", "AUTO WIN EVERY BATTLE", "nofight"),
    ("NOHURT", "HP NEVER DECREASES", "nohurt"),
    ("NOBLOCK", "WALK THROUGH ANY TILE", "noblock"),
    ("FULL MP", "MP NEVER DECREASES", "full_mp"),
    ("NOCLASS", "ANY CHAR CAN CAST ANY SPELL", "no_class"),
    ("PEER", "P SHOWS THE MAP ANYWHERE, NO GEM", "free_peer"),
]

MAX_ALL_LABEL = "MAXALL"  # cheat.c:76-77 "MAX]ALL"
MAX_ALL_DESC = "MAX OUT EVERYTHING FOR EVERYONE"  # cheat.c:101-102


def open_cheat_menu(text_log: Any, party: Any = None) -> None:
    """Open the F10 cheat menu as an indexed text_log prompt (GBC docheat).

    An indexed "1-8" prompt stands in for GBC's cursor menu: the port's
    prompt pipeline is text based and a cursor widget would be overkill.
    """
    if not DEBUG_MODE:
        return

    for idx, (label, desc, attr) in enumerate(_MENU_ITEMS):
        state = "ON" if getattr(CHEATS, attr) else "OFF"
        text_log.add_message(f"{idx + 1}. {label} - {desc} [{state}]")
    max_all_key = len(_MENU_ITEMS) + 1
    text_log.add_message(f"{max_all_key}. {MAX_ALL_LABEL} - {MAX_ALL_DESC}")
    text_log.prompt(
        f"Cheat? (1-{max_all_key - 1}, {max_all_key}/M=Max all, Esc=cancel):",
        callback=lambda choice: _on_cheat_choice(text_log, party, choice),
        single_char=True,
    )


def _on_cheat_choice(text_log: Any, party: Any, choice: str) -> None:
    key = choice.strip().upper()
    if key in (str(len(_MENU_ITEMS) + 1), "M"):
        text_log.add_message(max_all(party))
        return
    for idx, (label, _desc, attr) in enumerate(_MENU_ITEMS):
        if key == str(idx + 1):
            setattr(CHEATS, attr, not getattr(CHEATS, attr))
            return
    # Unrecognised entry: the menu simply closes (GBC default: no-op).


def max_all(party: Any) -> str:
    """One-shot ``domaxall`` (``cheat.c:441-479``) over every joined member.

    gold 9999, keys/gems/powders/torches 99, currHP/maxHP 9999, the four
    stats 99, food/exp 9999, level 99, every weapon and armor stack at 9,
    and the marks + cards flags all set (``markcard = 0xFF`` plus the
    ``party_specials = 0x0F`` special-item bits). No mp field is touched:
    GBC's domaxall (cheat.c:441-479) never writes one.
    """
    for member in getattr(party, "members", []) or []:
        char = getattr(member, "character", member)
        char.gold = 9999
        char.keys = 99
        char.gems = 99
        char.torches = 99
        char.powder = 99
        char.max_hp = 9999
        char.hp = 9999
        char.str = 99
        char.dex = 99
        char.int = 99
        char.wis = 99
        char.food = 9999
        char.exp = 9999
        char.level = 99
        weapons = getattr(char, "weapons", None)
        if weapons is not None:
            for wt in weapons:
                weapons[wt] = 9
        armors = getattr(char, "armors", None)
        if armors is not None:
            for at in armors:
                armors[at] = 9
        if getattr(char, "marks", None) is not None:
            char.marks = [1, 1, 1, 1]
        if getattr(char, "cards", None) is not None:
            char.cards = [1, 1, 1, 1]
    exodus_cards = getattr(party, "exodus_cards_status", None)
    if exodus_cards is not None:
        party.exodus_cards_status = 0xF
    return "MAX ALL: everything maxed out for everyone."


def apply_full_mp(member: Any) -> None:
    """FULL MP hook: top the caster's mp up to max when the flag is on.

    Called at each cast-prompt open before spell selection — the single
    central helper behind ``magic.prompt_cast_party`` and the combat
    screen's own cast prompt.
    """
    if not CHEATS.full_mp:
        return
    char = getattr(member, "character", member)
    max_mp = getattr(char, "max_mp", None)
    if max_mp:
        char.mp = max_mp
