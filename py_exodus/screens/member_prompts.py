"""Shared member-prompt flows used by every screen: ready weapon, wear
armor, and the modify-order exchange.

Java truth: these commands route through ``SecondaryInputProcessor`` /
``NewOrderInputAdapter`` on every screen — the overworld
(GameScreen.java:608-613) and the dungeon (DungeonScreen.java:1011-1013)
share one member-selection flow, so the Python implementation lives in one
place. ``turn_callback`` mirrors the ``finishTurn`` that Java's input
adapters run when a selection key finally leaves the flow (ReadyWearInputAdapter.java
ends with ``screen.finishTurn(currentX, currentY)`` for every keypress).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from py_exodus.constants import ArmorType, WeaponType

if TYPE_CHECKING:
    from py_exodus.entities.party import Party
    from py_exodus.ui.text_log import TextLog


def _noop() -> None:
    """Default turn callback: no turn is consumed."""
    return None


def _parse_index(raw: str) -> int:
    """Return a 0-based member index from a 1-4 answer, or -1."""
    try:
        idx = int(raw.strip()) - 1
    except ValueError:
        return -1
    return idx


def prompt_ready_weapon(
    text_log: TextLog,
    party: Party,
    asset_mgr: object | None,
    turn_callback: Callable[[], None] | None = None,
) -> None:
    """Ready Weapon: member 1-4, then an A-P weapon letter.

    Java truth: SecondaryInputProcessor.java:419-437 (R branch routes to
    ReadyWearInputAdapter.java, whose keyUp always runs finishTurn after the
    letter is handled).
    """
    if turn_callback is None:
        turn_callback = _noop

    def _on_member(m_str: str) -> None:
        idx = _parse_index(m_str)
        m = party.get_member(idx)
        if m is None:
            text_log.add_message("Invalid member #!")
            turn_callback()  # Java: the sip keyUp tail consumes the turn
            return

        weapon_types = list(WeaponType)
        text_log.add_message(f"-- Ready Weapon for {m.name} --")
        for w_idx, wt in enumerate(weapon_types):
            letter = chr(ord('A') + w_idx)
            if wt == WeaponType.NONE:
                text_log.add_message(f"{letter} - Hands")
                continue
            cnt = m.weapons.get(wt, 0)
            is_equipped = (m.weapon == wt)
            if cnt > 0 or is_equipped:
                status_tag = " (readied)" if is_equipped else f" ({cnt})"
                text_log.add_message(f"{letter} - {wt.name.capitalize()}{status_tag}")

        def _on_weap(w_code: str) -> None:
            c = w_code.strip().upper()
            if not c:
                turn_callback()  # ReadyWearInputAdapter: finishTurn for every key
                return
            w_idx = ord(c[0]) - ord('A')
            if 0 <= w_idx < len(weapon_types):
                success = m.ready_weapon(w_idx, asset_mgr)
                if success:
                    text_log.add_message(f"Success! {m.name} readied {m.weapon.name}.")
                else:
                    text_log.add_message("Cannot ready that weapon!")
            else:
                text_log.add_message("Invalid weapon selection!")
            turn_callback()  # ReadyWearInputAdapter: finishTurn for every key

        text_log.prompt("Ready Weapon? (A-P): ", callback=_on_weap, single_char=True)

    text_log.prompt("Ready Weapon: Which member? (1-4): ", callback=_on_member, single_char=True)


def prompt_wear_armor(
    text_log: TextLog,
    party: Party,
    asset_mgr: object | None,
    turn_callback: Callable[[], None] | None = None,
) -> None:
    """Wear Armor: member 1-4, then an A-H armor letter.

    Java truth: SecondaryInputProcessor.java:419-437 (W branch) routes to
    ReadyWearInputAdapter.java, whose keyUp always runs finishTurn after the
    letter is handled.
    """
    if turn_callback is None:
        turn_callback = _noop

    def _on_member(m_str: str) -> None:
        idx = _parse_index(m_str)
        m = party.get_member(idx)
        if m is None:
            text_log.add_message("Invalid member #!")
            turn_callback()  # Java: the sip keyUp tail consumes the turn
            return

        armor_types = list(ArmorType)
        text_log.add_message(f"-- Wear Armor for {m.name} --")
        for a_idx, at in enumerate(armor_types):
            letter = chr(ord('A') + a_idx)
            if at == ArmorType.NONE:
                text_log.add_message(f"{letter} - Skin")
                continue
            cnt = m.armors.get(at, 0)
            is_equipped = (m.armor == at)
            if cnt > 0 or is_equipped:
                status_tag = " (worn)" if is_equipped else f" ({cnt})"
                text_log.add_message(f"{letter} - {at.name.capitalize()}{status_tag}")

        def _on_arm(a_code: str) -> None:
            c = a_code.strip().upper()
            if not c:
                turn_callback()  # ReadyWearInputAdapter: finishTurn for every key
                return
            a_idx = ord(c[0]) - ord('A')
            if 0 <= a_idx < len(armor_types):
                success = m.wear_armor(a_idx, asset_mgr)
                if success:
                    text_log.add_message(f"Success! {m.name} wears {m.armor.name}.")
                else:
                    text_log.add_message("Cannot wear that armor!")
            else:
                text_log.add_message("Invalid armor selection!")
            turn_callback()  # ReadyWearInputAdapter: finishTurn for every key

        text_log.prompt("Wear Armor? (A-H): ", callback=_on_arm, single_char=True)

    text_log.prompt("Wear Armor: Which member? (1-4): ", callback=_on_member, single_char=True)


def prompt_modify_order(
    text_log: TextLog,
    party: Party,
    turn_callback: Callable[[], None] | None = None,
) -> None:
    """Modify Order: exchange member 1-4 with member 1-4.

    Java truth: BaseScreen.java:165-204 NewOrderInputAdapter — M logs
    "Modify Order:" / "exchange #:", a 1-4 digit takes the first exchange
    slot, a second digit (or any other key) swaps and ends the flow. The
    adapter calls finishTurn only from GameScreen, so callers on the
    overworld pass a turn callback and dungeon callers do not.
    """
    text_log.add_message("Modify Order:")
    text_log.add_message("exchange #:")

    def _on_first(p1_str: str) -> None:
        p1 = _parse_index(p1_str)
        if not (0 <= p1 < len(party.members)):
            text_log.add_message("What?")
            if turn_callback is not None:
                turn_callback()  # Java: "What?" still ends the adapter
            return

        def _on_second(p2_str: str) -> None:
            p2 = _parse_index(p2_str)
            if not (0 <= p2 < len(party.members)):
                text_log.add_message("What?")
                if turn_callback is not None:
                    turn_callback()  # Java: "What?" ends the adapter
                return

            party.swap_members(p1, p2)
            if turn_callback is not None:
                turn_callback()

        text_log.prompt("With member #? (1-4): ", callback=_on_second, single_char=True)

    text_log.prompt("Modify Order: Exchange member #? (1-4): ", callback=_on_first, single_char=True)
