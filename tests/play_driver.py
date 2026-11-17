"""Headless play driver: drive the real StateMachine with key sequences.

This is a plain test-helper module (imported by tests; NOT a pytest plugin and
NOT collected as a test module). ``PlaySession`` boots the same screens the
test suite constructs by hand, then routes ``pygame.event.Event(KEYDOWN, ...)``
events through ``StateMachine.handle_event`` so every screen — overworld,
town, dungeon, combat, vendors — behaves exactly as it does in the harness
tests, while the driver mirrors what those tests read from
``screen.text_log.history`` into a running transcript.

Booting conventions (mirrored from the existing tests):
- ``PlaySession().start()`` takes the real StartScreen "Journey Onward" flow
  (``K_1``), which resumes ``saves/party.json`` into the overworld — the same
  shortcut ``tests/test_book_of_lore.py::test_f1_reaches_a_real_game_screen``
  relies on. Requires the repo-root save to exist.
- ``start(party=...)`` builds ``OverworldScreen`` directly (the convention in
  ``tests/test_game_loop.py``) with ``map_id`` (default 0, the overworld).
- ``enter_combat()`` mirrors the ``test_combat_parity.py`` CombatScreen
  fixture: a real ``ConflictMap`` via ``MapLoader.load_conflict_map`` and an
  explicit ``context_map_id``.

Key token map for ``press()`` / ``press_seq()``:
- single letters: ``"A"``..``"Z"`` -> ``pygame.K_a``..``pygame.K_z``
- digits: ``"0"``..``"9"`` -> ``pygame.K_0``..``pygame.K_9``
- Arrow-by-name (compass naming, matching the game's direction prompts):
  ``N`` -> ``K_UP``, ``S`` -> ``K_DOWN``, ``E`` -> ``K_RIGHT``,
  ``W`` -> ``K_LEFT``
- Literal arrow names also work: ``UP``/``DOWN``/``LEFT``/``RIGHT``
- Named specials: ``SPACE``, ``ESC``/``ESCAPE``, ``RETURN``/``ENTER``,
  ``BACKSPACE``, ``PAGEUP``, ``PAGEDOWN``, ``F1``, ``F10``
"""
from __future__ import annotations

import pygame

from py_exodus.assets import AssetManager
from py_exodus.state_machine import StateMachine

# Compass arrow naming plus literal arrow names and the specials the screens
# themselves bind.
KEY_TOKENS: dict[str, int] = {
    "N": pygame.K_UP,
    "S": pygame.K_DOWN,
    "E": pygame.K_RIGHT,
    "W": pygame.K_LEFT,
    "UP": pygame.K_UP,
    "DOWN": pygame.K_DOWN,
    "LEFT": pygame.K_LEFT,
    "RIGHT": pygame.K_RIGHT,
    "SPACE": pygame.K_SPACE,
    "ESC": pygame.K_ESCAPE,
    "ESCAPE": pygame.K_ESCAPE,
    "RETURN": pygame.K_RETURN,
    "ENTER": pygame.K_RETURN,
    "BACKSPACE": pygame.K_BACKSPACE,
    "PAGEUP": pygame.K_PAGEUP,
    "PAGEDOWN": pygame.K_PAGEDOWN,
    "F1": pygame.K_F1,
    "F10": pygame.K_F10,
}


def resolve_key(token: str | int) -> int:
    """Map a driver key token (or a raw ``pygame.K_*`` int) to a key constant."""
    if isinstance(token, int):
        return token
    if not isinstance(token, str):
        raise TypeError(f"key token must be a str or pygame.K_* int, got {token!r}")
    # Compass arrow names win over the same letters; pass pygame.K_n etc. to
    # send the literal letter key.
    code = KEY_TOKENS.get(token.upper())
    if code is not None:
        return code
    if len(token) == 1:
        ch = token.lower()
        if ch.isdigit():
            return pygame.K_0 + int(ch)
        if ch.isalpha():
            return pygame.K_a + ord(ch) - ord("a")
    raise ValueError(
        f"unknown key token {token!r}: use a single letter/digit, compass arrows "
        "N/S/E/W, literal UP/DOWN/LEFT/RIGHT, or one of "
        + ", ".join(sorted(t for t in KEY_TOKENS if t not in "NEWS"))
    )


def _unicode_for(token: str) -> str | None:
    """Best-effort ``unicode`` attribute, mirroring real KEYDOWN payloads."""
    if not isinstance(token, str) or len(token) != 1:
        return None
    ch = token.lower()
    if ch.isalnum():
        return ch
    if token == "SPACE":
        return " "
    return None


class PlaySession:
    """A headless game session driven by key events, with a running transcript."""

    def __init__(self, asset_mgr: AssetManager | None = None) -> None:
        # Idempotent headless init (the suite's init_pygame fixtures do the
        # same); never quit here so co-existing tests keep their pygame state.
        if not pygame.get_init():
            pygame.init()
        if not pygame.font.get_init():
            pygame.font.init()

        if asset_mgr is None:
            asset_mgr = AssetManager()
            asset_mgr.load_tiles()
            asset_mgr.load_xml_definitions()
        self.asset_mgr = asset_mgr

        self.sm: StateMachine | None = None
        self.party = None
        self._transcript: list[str] = []
        # id(text_log) -> (log, consumed history length); the strong ref
        # prevents id reuse from two text_log lifecycles.
        self._seen: dict[int, tuple] = {}
        # id(text_log) -> last captured prompt text (reset when not waiting).
        self._last_prompt: dict[int, str | None] = {}

    # --- booting ---------------------------------------------------------

    def start(self, map_id: int | None = None, party=None) -> "PlaySession":
        """Boot the real StateMachine and land on the overworld screen.

        With no ``party``, takes the genuine StartScreen -> Journey Onward
        (K_1) flow, resuming ``saves/party.json`` (repo-root save short cut).
        With ``party``, builds ``OverworldScreen`` directly at ``map_id``
        (default 0), mirroring tests/test_game_loop.py. Returns self.
        """
        self.sm = StateMachine(asset_mgr=self.asset_mgr)

        from py_exodus.screens.overworld import OverworldScreen

        if party is None:
            # StartScreen "Journey Onward": K_1 resumes the on-disk party save.
            self.sm.handle_event(pygame.event.Event(
                pygame.KEYDOWN, key=pygame.K_1, unicode="1"))
            self._drain()
            if not isinstance(self.sm.current_screen, OverworldScreen):
                raise RuntimeError(
                    "Journey Onward did not reach the overworld; saves/party.json "
                    "is missing or holds no party. Pass party= to boot directly."
                )
        else:
            overworld = OverworldScreen(
                party=party,
                map_id=0 if map_id is None else map_id,
                asset_mgr=self.asset_mgr,
            )
            self.sm.set_screen(overworld)
            self._drain()
            if not isinstance(self.sm.current_screen, OverworldScreen):
                raise RuntimeError(
                    f"booted screen {self.sm.current_screen!r} is not an OverworldScreen"
                )

        self.party = self.sm.current_screen.party
        return self

    def enter_combat(
        self,
        creature_tile: str = "orc",
        combat_map_name: str = "CNFLCT_A.ULT",
        context_map_id: int | None = None,
        monster_count: int | None = None,
        party=None,
    ) -> "PlaySession":
        """Push a real CombatScreen (test_combat_parity.py fixture pattern).

        Loads the named conflict map with MapLoader and passes
        ``context_map_id`` through (e.g. 2 for the Castle of Death rules).
        """
        if self.sm is None:
            raise RuntimeError("call start() before enter_combat()")
        from py_exodus.screens.combat_screen import CombatScreen
        from py_exodus.world.loader import MapLoader

        combat_map = MapLoader(self.asset_mgr).load_conflict_map(combat_map_name)
        combat = CombatScreen(
            party=party if party is not None else self.party,
            combat_map=combat_map,
            creature_tile=creature_tile,
            asset_mgr=self.asset_mgr,
            monster_count=monster_count,
            context_map_id=context_map_id,
        )
        self.sm.push_screen(combat)
        self._drain()
        return self

    # --- input -----------------------------------------------------------

    def press(self, key: str | int) -> None:
        """Send one KEYDOWN event to the active screen, then drain the log."""
        if self.sm is None:
            raise RuntimeError("call start() before press()")
        screen_before = self.screen
        token = key if isinstance(key, str) else None
        keycode = resolve_key(key)
        attrs: dict = {"key": keycode}
        unicode = _unicode_for(token)
        if unicode is not None:
            attrs["unicode"] = unicode
        self.sm.handle_event(pygame.event.Event(pygame.KEYDOWN, **attrs))
        if screen_before is not None and screen_before is not self.screen:
            self._drain(screen_before)
        self._drain()

    def press_seq(self, seq: str) -> None:
        """Send a space-separated sequence of key tokens, one event each."""
        for token in seq.split():
            self.press(token)

    # --- observation ------------------------------------------------------

    @property
    def screen(self):
        """The currently active screen (or None before start())."""
        return self.sm.current_screen if self.sm is not None else None

    @property
    def transcript(self) -> list[str]:
        """Every text_log line observed so far, in order, tagged.

        Message/history lines are prefixed ``[msg] ``; interactive prompts
        (``text_log.prompt`` opening) are prefixed ``[prompt] ``. Sourced the
        same way the harness tests read the log: ``screen.text_log.history``
        plus ``text_log.is_waiting_for_input`` / ``current_prompt``.
        """
        return list(self._transcript)

    @property
    def active_member(self) -> str | None:
        """Name of the member taking a turn, on combat screens; None elsewhere.

        Combat screens expose the arena's active member through
        ``CombatScreen.active_party_member`` (backed by
        ``arena.active_party_member_idx``); non-combat screens have no such
        attribute and yield None.
        """
        member = getattr(self.screen, "active_party_member", None)
        if member is None:
            return None
        return getattr(member, "name", None)

    @property
    def is_waiting_for_input(self) -> bool:
        """True while the active screen's text log holds an open prompt."""
        log = getattr(self.screen, "text_log", None)
        return bool(log is not None and log.is_waiting_for_input)

    # --- transcript plumbing ----------------------------------------------

    def _drain(self, screen=None) -> None:
        """Mirror any not-yet-seen text_log activity into the transcript."""
        screen = self.screen if screen is None else screen
        if screen is None:
            return
        if hasattr(screen, "flush_animations"):
            screen.flush_animations()
        log = getattr(screen, "text_log", None)
        if log is None:
            return

        key = id(log)
        record = self._seen.get(key)
        if record is None or record[0] is not log:
            record = (log, 0)
        history = log.history
        seen_n = min(record[1], len(history))  # clear() rewinds the baseline
        for line in history[seen_n:]:
            self._transcript.append(f"[msg] {line}")
        self._seen[key] = (log, len(history))

        if log.is_waiting_for_input and log.current_prompt:
            last = self._last_prompt.get(key)
            if last is None or last != log.current_prompt:
                self._transcript.append(f"[prompt] {log.current_prompt}")
                self._last_prompt[key] = log.current_prompt
        else:
            self._last_prompt[key] = None
