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
            if c:
                w_idx = ord(c[0]) - ord('A')
                # Java SecondaryInputProcessor.java:465-483 — for any key in
                # A..P the adapter logs exactly "Success!" or "Failed!"; other
                # keys log nothing. The enum covers all of A..P, but a letter
                # past the list reproduces Java's readyWeapon(…)==false.
                if 0 <= w_idx < len(weapon_types):
                    success = m.ready_weapon(w_idx, asset_mgr)
                    text_log.add_message("Success!" if success else "Failed!")
                else:
                    text_log.add_message("Failed!")
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
            if c:
                a_idx = ord(c[0]) - ord('A')
                # Java SecondaryInputProcessor.java:465-483 — the key test is
                # A..P for both flows, so an armor letter past A..H falls into
                # wearArmor(…)==false and logs "Failed!" exactly like Java.
                if 0 <= a_idx < len(armor_types):
                    success = m.wear_armor(a_idx, asset_mgr)
                    text_log.add_message("Success!" if success else "Failed!")
                else:
                    text_log.add_message("Failed!")
            turn_callback()  # ReadyWearInputAdapter: finishTurn for every key

        text_log.prompt("Wear Armor? (A-H): ", callback=_on_arm, single_char=True)

    text_log.prompt("Wear Armor: Which member? (1-4): ", callback=_on_member, single_char=True)


def prompt_modify_order(
    text_log: TextLog,
    party: Party,
    turn_callback: Callable[[], None] | None = None,
    exchange_label: str = "exchange #:",
) -> None:
    """Modify Order: exchange member 1-4 with member 1-4.

    Java truth: BaseScreen.java:165-204 NewOrderInputAdapter — M logs
    "Modify Order:" and an exchange label, a 1-4 digit takes the first
    exchange slot, a second digit (or any other key) swaps and ends the
    flow. The adapter calls finishTurn only from GameScreen, so callers on
    the overworld/town pass a turn callback and dungeon callers do not.
    GameScreen.java:601 prints the corrected "exchange #:" while
    DungeonScreen.java:1028 keeps Java's typo "exhange #:" — pass
    ``exchange_label="exhange #:"`` from the dungeon.
    """
    text_log.add_message("Modify Order:")
    text_log.add_message(exchange_label)

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


def prompt_whose_item(
    text_log: TextLog,
    party: Party,
    query: str,
    attr: str,
    on_spent: Callable[[object], None],
    turn_callback: Callable[[], None] | None = None,
) -> None:
    """LairWare NegateTime / PeerGem (UltimaMain.c:2122-2159): ask whose
    item, then that member spends one (``Player[rosNum][n] < 1`` -> "None
    left!"). No CheckAlive: a dead member's powder or gem works too. A key
    outside 1-4 just ends the command. The turn passes either way."""
    if turn_callback is None:
        turn_callback = _noop

    def _on_member(m_str: str) -> None:
        member = party.get_member(_parse_index(m_str))
        if member is not None:
            if getattr(member, attr, 0) < 1:
                text_log.add_message("None left!")
            else:
                setattr(member, attr, getattr(member, attr) - 1)
                on_spent(member)
        turn_callback()

    text_log.prompt(query, callback=_on_member, single_char=True, on_cancel=turn_callback)


_HAND_SUPPLIES = {"G": "gems", "K": "keys", "P": "powder", "T": "torches"}


def prompt_hand(text_log: TextLog, party: Party) -> None:
    """LairWare HandEquip (UltimaMain.c:1744-1944): from, to, then
    F(ood)/G(old) with an amount (the taker capped at 9999), E(quipment)
    G/K/P/T with a count (capped at 99), or one W(eapon) B-P / A(rmour) B-H.
    No CheckAlive. More than the giver has is "Not enough!", past the cap
    "Too much!"; the readied weapon or worn armour stays ("In use!") unless
    the giver holds another. The turn is taken at the H press."""
    from py_exodus.special_commands import add_item

    def _members(p1: int, p2: int) -> None:
        if p1 == p2:
            return  # ErrorTone only (UltimaMain.c:1775-1778)
        giver, taker = party.members[p1], party.members[p2]

        def _move(attr: str, cap: int, raw: str) -> None:
            try:
                value = int(raw.strip() or "0")
            except ValueError:
                value = 0
            if value > getattr(giver, attr):
                text_log.add_message("Not enough!")
                return
            if getattr(taker, attr) + value > cap:
                text_log.add_message("Too much!")
                return
            setattr(giver, attr, getattr(giver, attr) - value)
            setattr(taker, attr, getattr(taker, attr) + value)
            text_log.add_message("Done!")

        def _gear(letter: str, order: list, stacks_attr: str, readied_attr: str, top: str) -> None:
            c = letter.strip().upper()
            if not c or not ("B" <= c <= top):
                text_log.add_message("None!")
                return
            kind = order[ord(c) - ord("A")]
            stacks = getattr(giver, stacks_attr)
            if int(stacks.get(kind, 0)) < 1:
                text_log.add_message("In use!" if getattr(giver, readied_attr) == kind else "None!")
                return
            stacks[kind] -= 1
            add_item(getattr(taker, stacks_attr), kind, getattr(taker, readied_attr))
            text_log.add_message("Done!")

        def _on_what(what: str) -> None:
            c = what.strip().upper()
            if c in ("F", "G"):
                attr = "food" if c == "F" else "gold"
                text_log.prompt("Amount-", callback=lambda r: _move(attr, 9999, r))
            elif c == "E":
                def _on_supply(s: str) -> None:
                    attr = _HAND_SUPPLIES.get(s.strip().upper())
                    if attr is None:
                        text_log.add_message("None!")
                        return
                    text_log.prompt("How many-", callback=lambda r: _move(attr, 99, r))

                text_log.prompt("G,K,P,T:", callback=_on_supply, single_char=True)
            elif c == "W":
                text_log.prompt(
                    "Which weapon:", single_char=True,
                    callback=lambda r: _gear(r, list(WeaponType), "weapons", "weapon", "P"),
                )
            elif c == "A":
                text_log.prompt(
                    "Which armour:", single_char=True,
                    callback=lambda r: _gear(r, list(ArmorType), "armors", "armor", "H"),
                )
            else:
                text_log.add_message("None!")

        text_log.prompt("F,G,E,W,A:", callback=_on_what, single_char=True)

    def _on_from(f_str: str) -> None:
        p1 = _parse_index(f_str)
        if not (0 <= p1 < len(party.members)):
            text_log.add_message("No such player!")
            return

        def _on_to(t_str: str) -> None:
            p2 = _parse_index(t_str)
            if not (0 <= p2 < len(party.members)):
                text_log.add_message("No such player!")
                return
            _members(p1, p2)

        text_log.prompt("HAND> To plr- (1-4):", callback=_on_to, single_char=True)

    text_log.prompt("HAND> From plr- (1-4):", callback=_on_from, single_char=True)


def show_ztats(text_log: TextLog, stats_panel, party: Party, index: int) -> None:
    """DoStats (UltimaMacIF.c:1385-1395): the member's stats, modal; the
    next key closes them (each screen swallows it). ``inspect_index`` names
    the member whose Ztats window the screen draws over its map pane
    (py_exodus/ui/ztats_view.py); the log gets one line."""
    member = party.get_member(index)
    if member is None:
        return
    stats_panel.inspect_index = index
    text_log.add_message(f"Zstats: {member.name} ({member.profession.name})")


def prompt_ztats(
    text_log: TextLog, stats_panel, party: Party, on_done: Callable[[], None] = _noop
) -> None:
    """LairWare Stats(0, 0) (UltimaMain.c:2592-2602): ``UPrintMessage(105);
    chnum = GetChar(); if (chnum < 1 || chnum > 4) { UPrintWin("\\p\\n");
    return; }`` then DoStats for that member only. ``on_done`` runs once the
    question is answered or refused (the dungeon's dungeonmech turn)."""

    def _on_member(raw: str) -> None:
        try:
            n = int(raw.strip())
        except ValueError:
            n = 0
        if 1 <= n <= 4:
            show_ztats(text_log, stats_panel, party, n - 1)
        on_done()

    text_log.prompt("Ztats for #-", callback=_on_member, single_char=True, on_cancel=on_done)
