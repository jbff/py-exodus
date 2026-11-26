"""Dungeon exploration screen: the Stone first-person view, HUD, and combat triggers."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pygame

from py_exodus import debug
from py_exodus.assets import MAP_NAME_TO_ID
from py_exodus.constants import (
    BASE_HEIGHT,
    BASE_WIDTH,
    Direction,
    MapType,
    Spell,
)
from py_exodus.entities.party import PartyDeathException
from py_exodus import special_commands
from py_exodus.screens.base import BaseScreen
from py_exodus.screens.member_prompts import (
    prompt_hand,
    prompt_modify_order,
    prompt_ztats,
    prompt_whose_item,
    prompt_ready_weapon,
    prompt_wear_armor,
)
from py_exodus.ui.stats_panel import StatsPanel
from py_exodus.ui.text_log import (
    EGA_BLACK,
    EGA_LIGHT_GRAY,
    EGA_WHITE,
    EGA_YELLOW,
    TextLog,
    get_hud_font,
)
from py_exodus.world.dungeon import (
    DungeonCamera,
    DungeonEvent,
    DungeonEventType,
    DungeonState,
)

if TYPE_CHECKING:
    from py_exodus.assets import AssetManager
    from py_exodus.audio import AudioManager
    from py_exodus.entities.party import Party
    from py_exodus.world.map import DungeonMap


# LairWare DungeonStart (UltimaDngn.c:134-157): letters that are NotDngCmd.
_NOT_DNG_CMD_KEYS = frozenset(
    getattr(pygame, f"K_{c}") for c in "abefqlstux"
)


class DungeonScreen(BaseScreen):
    """First-person dungeon navigation screen (the Stone view)."""

    #: Where spells are cast from here (the Ztats window's spell chips).
    spell_map_type = "dungeon"

    allows_quick_reference = True

    def __init__(
        self,
        party: Party,
        dungeon_map: DungeonMap | None = None,
        map_id: int | str = 14,
        asset_mgr: AssetManager | None = None,
        audio: AudioManager | None = None,
        return_screen: BaseScreen | None = None,
        start_x: int = 1,
        start_y: int = 1,
        start_z: int = 0,
        # LairWare Enter (UltimaMain.c:1430-1433): level 1, (1, 1), heading
        # 1 (east).
        start_dir: Direction = Direction.EAST,
        **kwargs: Any,
    ) -> None:
        super().__init__(return_screen=return_screen, **kwargs)
        self.party = party
        self.asset_mgr = asset_mgr
        self.audio = audio
        self.map_id = map_id

        # Load map if not provided
        self.dungeon_map = dungeon_map
        if self.dungeon_map is None and self.asset_mgr is not None:
            self._load_map()

        # Fallback empty dungeon map if none could be loaded
        if self.dungeon_map is None:
            from py_exodus.world.map import DungeonMap

            try:
                fallback_id = int(self.map_id)
            except (TypeError, ValueError):
                fallback_id = MAP_NAME_TO_ID.get(str(self.map_id).upper(), 0)
            self.dungeon_map = DungeonMap(
                id=fallback_id, width=16, height=16, levels=8, name="Dungeon", fname="perinian.json"
            )

        self.state = DungeonState(
            dmap=self.dungeon_map,
            start_x=start_x,
            start_y=start_y,
            start_z=start_z,
            start_dir=start_dir,
            party=self.party,
            asset_manager=self.asset_mgr,
        )
        self.camera = DungeonCamera(viewport_size=176, asset_mgr=self.asset_mgr)
        self.stats_panel = StatsPanel(asset_mgr=self.asset_mgr)
        self.text_log = TextLog(max_lines=5, wrap_width=64)
        # DungeonStart's idle wait (UltimaDngn.c:110-121), in game seconds.
        self._idle_time = 0.0
        # The level map (LairWare DrawMiniDng): up after a Peer (P) or a
        # Vieda, until any key.  No free overhead plan (user ruling
        # 2026-11-26): the old overlay is gone.
        self.gem_view_active = False
        self._gem_view_time = 0.0
        # dPeer's turn (dungeonmech) follows the map, not the gem.
        self._gem_turn_pending = False
        # The close-up that is up (LairWare ImageDisplay 5/6/8 until
        # ImageGoAway, UltimaDngn.c:212-318): "fountain" and "rod" for the
        # length of their question, "timelord" until a key or a click.
        self._picture: str | None = None

        # LairWare Enter (UltimaMain.c:1424-1434): "Enter " (Messages 32)
        # then "dungeon!" (33), nothing more (user ruling 2026-11-25).
        self.text_log.add_message("Enter dungeon!")

    def _load_map(self) -> None:
        try:
            from py_exodus.world.loader import MapLoader

            loader = MapLoader(self.asset_mgr)
            loaded = loader.load_map(self.map_id)
            if hasattr(loaded, "levels"):
                self.dungeon_map = loaded
        except Exception:
            pass

    def on_enter(self) -> None:
        super().on_enter()
        # Back from another screen (the Book, a fight): the command wait
        # starts its idle count afresh (UltimaMain.c:1040).
        self._idle_time = 0.0
        if self.audio is not None:
            self.audio.play_music("dungeon")

    def handle_event(self, event: pygame.event.Event) -> None:
        # Mouse wheel scrolls the shared text log back through history
        # (Java LogScrollPane affordance; wheel is never a dungeon command).
        # The level map owns all input: no scrolling under it (as the
        # surface Peer), and a click ends it like any key: LairWare
        # DrawMiniDng waits on ``GetKeyMouse(0) | Button()``
        # (UltimaGraphics.c:1581).
        if event.type == pygame.MOUSEWHEEL:
            if not self.gem_view_active:
                self.text_log.handle_wheel(event)
            return
        if event.type == pygame.MOUSEBUTTONDOWN:
            # Buttons 4 and 5 are the wheel's legacy events, not clicks.
            if getattr(event, "button", 1) not in (1, 2, 3):
                return
            if self.gem_view_active:
                self._idle_time = 0.0
                self._close_gem_view()
            elif self._picture == "timelord":
                self._idle_time = 0.0
                self._picture = None  # WaitKeyMouse (UltimaDngn.c:218)
            return

        if event.type != pygame.KEYDOWN:
            return
        # Any key ends DungeonStart's wait; the next one sets nextPassTime
        # afresh (UltimaDngn.c:110, 126-127).
        self._idle_time = 0.0

        # LairWare DoStats (UltimaMacIF.c:1385-1395): Ztats waits in its own
        # loop (``while (gStatsActive) { GetKeyMouse(1); if (gKeyPress)
        # gStatsActive = FALSE; }``), so nothing in the world acts while it
        # is up and the key that ends it, any key, is swallowed.
        if self.stats_panel.inspect_index is not None:
            self.stats_panel.inspect_index = None
            # Stats returns, then dungeonmech (UltimaDngn.c:159-161).
            self._run_fixture()
            return

        # LairWare DrawMiniDng (UltimaGraphics.c:1571-1584) waits in its own
        # loop: the key that ends the map is swallowed, the 3D view returns.
        if self.gem_view_active:
            self._close_gem_view()
            return

        # The Time Lord's picture (UltimaDngn.c:213-222): ``WaitKeyMouse();
        # ImageGoAway(); ... DrawDungeon();`` -- the key is swallowed.
        if self._picture == "timelord":
            self._picture = None
            return

        if self.text_log.is_waiting_for_input:
            self.text_log.handle_event(event)
            if not self.text_log.is_waiting_for_input:
                self._picture = None  # the question is over: ImageGoAway
            self._run_fixture()
            return

        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): debug cheat
        # harness (GBC cheat.c:768-825 docheat) — F10 opens the cheat menu in
        # --debug mode only; non-debug F10 stays inert.
        if debug.DEBUG_MODE and event.key == pygame.K_F10:
            debug.open_cheat_menu(self.text_log, self.party)
            return

        self._dispatch_command(event)
        self._run_fixture()

    def _dispatch_command(self, event: pygame.event.Event) -> None:
        """One dungeon command (LairWare DungeonStart's switch,
        UltimaDngn.c:130-182); each one ends in dungeonmech."""

        # PageUp/PageDown always scroll the text log back (arrow keys scroll
        # only inside the log's own prompt handling, when they cannot act as
        # direction/command answers).
        if self.text_log.handle_scroll_key(event.key):
            return

        # Movement and navigation keys: Arrow keys and Keypad ONLY (no WASD)
        # LEFT/RIGHT turn in place and take the turn (LairWare Left/Right,
        # UltimaDngn.c:172-177, 183); UP steps forward; DOWN steps one square
        # *backward* in the current facing (with wrap) — it is not a 180
        # degree turn.
        if event.key in (pygame.K_UP, pygame.K_KP8):
            evt = self.state.move_forward()
            self._process_event(evt)
        elif event.key in (pygame.K_DOWN, pygame.K_KP2):
            evt = self.state.move_backward()
            self._process_event(evt)
        elif event.key in (pygame.K_LEFT, pygame.K_KP4):
            evt = self.state.turn_left()
            self._process_event(evt)
        elif event.key in (pygame.K_RIGHT, pygame.K_KP6):
            evt = self.state.turn_right()
            self._process_event(evt)
        elif event.key == pygame.K_k:
            # Ladders consume a turn (GBC ult3.c:1388-1429; LairWare dKlimb
            # ends in dungeonmech too, UltimaDngn.c:144, 183).
            evt = self.state.klimb_up()
            self._process_event(evt)
        elif event.key == pygame.K_d:
            # Ladders consume a turn (GBC ult3.c:1388-1429; LairWare dDescend
            # ends in dungeonmech too, UltimaDngn.c:137, 183).
            evt = self.state.klimb_down()
            self._process_event(evt)
        elif event.key == pygame.K_i:
            self._use_torch()
        elif event.key == pygame.K_h:
            # LairWare HandEquip (UltimaDngn.c:141); the turn is taken at the
            # press (dungeonmech follows the command).
            self._consume_turn()
            prompt_hand(self.text_log, self.party)
        elif event.key == pygame.K_j:
            self._join_gold()
        elif event.key == pygame.K_n:
            self._negate_time()
        elif event.key == pygame.K_y:
            self._prompt_yell()
        elif event.key == pygame.K_p:
            self._peer_gem()
        elif event.key == pygame.K_v:
            # Java DungeonScreen.java:1013-1023 — V toggles music and falls
            # through the keyUp tail (turn consumed).
            self._toggle_music()
        elif event.key == pygame.K_m:
            # LairWare ModifyOrder ends in dungeonmech (UltimaDngn.c:146,
            # 161, 183): the turn passes when the exchange is done.
            # Java's typo "exhange #:" (DungeonScreen.java:1028) stays.
            prompt_modify_order(
                self.text_log, self.party, exchange_label="exhange #:",
                turn_callback=self._consume_turn,
            )
        elif event.key == pygame.K_r:
            # R/W/C/O take their one dungeonmech pass (UltimaDngn.c:183) at
            # the press, so a cancelled prompt still takes it; the prompt
            # flow adds none.
            self._consume_turn()
            prompt_ready_weapon(self.text_log, self.party, self.asset_mgr)
        elif event.key == pygame.K_w:
            self._consume_turn()
            prompt_wear_armor(self.text_log, self.party, self.asset_mgr)
        elif event.key == pygame.K_c:
            self._consume_turn()
            self._cast_spell()
        elif event.key == pygame.K_o:
            # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): functional
            # Other command (GBC menucmd3.c:1019-1236; menucmd2.c:1440-1540)
            # — GBC's bribe/steal/dig are only offered OUTSIDE, so from a
            # dungeon they take the GBC noeffectdat refusal; pray/search/
            # score still run through the shared special_commands flows.
            # Like the other dungeon command prompts, the press consumes a
            # turn before the prompt opens.
            self._consume_turn()
            self._prompt_other()
        elif event.key == pygame.K_g:
            self._get_chest()
        elif event.key == pygame.K_z:
            # LairWare Stats (UltimaMain.c:2592-2602) asks whose Ztats, then
            # dungeonmech (UltimaDngn.c:159, 161, 183) takes the turn,
            # answered or not.
            prompt_ztats(self.text_log, self.stats_panel, self.party, on_done=self._consume_turn)
        elif event.key in _NOT_DNG_CMD_KEYS:
            # LairWare NotDngCmd (UltimaDngn.c:134-157, 492-495): A, B, E,
            # F, L, Q, S, T, U and X print message 172 and the error tone,
            # then dungeonmech takes the turn (161; ledger D-22).
            # USER RULING 2026-11-10: Q is no dungeon save (Q-save lives
            # only on the Sosaria overland).
            self.text_log.add_message("NOT A DNG CMD!")
            if self.audio is not None:
                self.audio.play_sfx("blocked")
            self._consume_turn()
        else:
            # Java DungeonScreen.java:1045-1049 + 1049-1050 — any other key
            # logs "Pass" and falls through to finishTurn.
            # USER RULING 2026-11-10: the dungeon Q-save (Java
            # DungeonScreen.java:976-986 — Keys.Q calls context.saveGame from
            # any dungeon level and logs "Saved Game." with the dungeon
            # coordinates) is DISABLED by ruling — a deliberate deviation
            # from Java. Q-save lives ONLY on the Sosaria overland
            # (OverworldScreen._save_game), so dungeon Q has no handler and
            # lands on this unhandled-key tail: it logs "Pass" and consumes
            # a turn. The dungeon `extra` save block was removed with it.
            self.text_log.add_message("Pass")
            self._consume_turn()

    def _run_fixture(self) -> None:
        """dungeonmech's fixture (UltimaDngn.c:211-341), once the command and
        its own prompts are done: every command while the party stands on
        a fixture (user ruling 2026-11-25, ledger D-12)."""
        if self.text_log.is_waiting_for_input or self.is_finished:
            return
        if self.stats_panel.inspect_index is not None:
            return  # Ztats is modal; the fixture follows when it closes
        if self.gem_view_active:
            return  # so is the level map
        if self.manager is not None and self.manager.current_screen is not self:
            return
        evt = self.state.take_fixture()
        if evt is None:
            return
        if evt.type == DungeonEventType.FOUNTAIN:
            self._ask_fountain()
        elif evt.type == DungeonEventType.MARK:
            self._ask_rod()
        else:
            self._process_event(evt)
            self._show_time_lord(evt)

    def _show_time_lord(self, evt: DungeonEvent) -> None:
        """UltimaDngn.c:213-222: ``ImageDisplay(8, TRUE); UPrintMessage(151);
        WaitKeyMouse(); ImageGoAway();`` -- his picture stays with his words
        until a key or a click. Autoplay answers every wait itself
        (realtime.autoplay_on), so it never holds for the picture."""
        from py_exodus.world import realtime
        from py_exodus.world.map import DungeonTile

        if evt.tile != DungeonTile.TIME_LORD or self.is_finished:
            return
        if self.manager is not None and self.manager.current_screen is not self:
            return
        if realtime.autoplay_on(self):
            return
        self._picture = "timelord"

    def _ask_fountain(self) -> None:
        """UltimaDngn.c:228-279: ``fountain: UPrintMessage(152); chnum =
        GetChar(); if (chnum < 1 || chnum > 4) { ... goto dungstart; }`` --
        a member drinks (the dead and ashes "Can't") and the question comes
        again; any other key leaves. The answers take no turn.

        The fountain's picture is up from ``ImageDisplay(5, TRUE)`` (224)
        to the ``ImageGoAway()`` of the key that leaves (233): for as long
        as the question is asked, and no longer."""
        self._picture = "fountain"

        def _on_who(who: str) -> None:
            self._picture = None
            try:
                n = int(who.strip())
            except ValueError:
                return
            if not 1 <= n <= 4:
                return
            member = self.party.get_member(n - 1)
            if member is None or member.is_disabled():
                self.text_log.add_message("Can't")
            else:
                try:
                    evt = self.state.drink_fountain(n - 1)
                except PartyDeathException:
                    evt = None
                if evt is not None:
                    self._process_event(evt)
                if self.check_party_death():
                    return
            self._ask_fountain()  # goto fountain

        self.text_log.prompt(
            "A fountain, who will drink? (1-4):", callback=_on_who, single_char=True
        )

    def _ask_rod(self) -> None:
        """UltimaDngn.c:300-318: ``UPrintMessage(161); chnum = GetChar();`` --
        one member touches the red-hot rod (the mark, then HPSubtract 50;
        LW has no CheckAlive, but a dead member is refused here: user
        ruling 2026-11-25, ledger D-26), or any other key leaves. Either way the prompt is
        done until the next command.

        The rod's picture is up from ``ImageDisplay(6, TRUE)`` (300) to the
        ``mark: ImageGoAway()`` every answer ends in (308-309)."""
        self._picture = "rod"

        def _on_who(who: str) -> None:
            self._picture = None
            try:
                n = int(who.strip())
            except ValueError:
                return
            if not 1 <= n <= 4 or self.party.get_member(n - 1) is None:
                return
            # USER-DIRECTED DEVIATION (ruling 2026-11-25; ledger D-26): LW's
            # brand case (UltimaDngn.c:300-318) has no CheckAlive, so a dead
            # member took the mark. Here a dead member is like a key
            # outside 1-4: no mark, no damage, the prompt closes.
            if self.party.get_member(n - 1).is_dead():
                return
            try:
                evt = self.state.touch_mark(n - 1)
            except PartyDeathException:
                evt = None
            if evt is not None:
                self._process_event(evt)
            self.check_party_death()

        self.text_log.prompt(
            "A red hot rod in the wall, who will touch? (1-4):",
            callback=_on_who, single_char=True,
        )

    def _prompt_other(self) -> None:
        """Other command from a dungeon (GBC menucmd3.c:1019-1236 subset).

        USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): GBC's bribe/steal/
        dig are OUTSIDE-only, so the dungeon refuses them with the GBC
        noeffectdat message; pray/search/score delegate to the shared
        py_exodus.special_commands flows.
        """
        self.text_log.prompt("Other Command? ", callback=self._run_other)

    def _run_other(self, cmd: str) -> None:
        """One Other word in the dungeon (O, or a yelled word)."""
        c = cmd.strip().upper()
        if not c:
            return
        if c in ("BRIBE", "STEAL", "DIG"):
            self.text_log.add_message(special_commands.NO_EFFECT)
        elif c == "PRAY":
            self.text_log.add_message(
                special_commands.do_pray(
                    self.state.x,
                    self.state.y,
                    self.map_id,
                    str(getattr(self.dungeon_map, "name", "") or ""),
                )
            )
        elif c == "SEARCH":
            special_commands.search_flow(
                self.text_log,
                self.party,
                self.state.x,
                self.state.y,
                self.dungeon_map,
            )
        else:
            self.text_log.add_message(f"'{c}': Nothing happened.")

    def _join_gold(self) -> None:
        """LairWare JoinGold (UltimaDngn.c:143; UltimaMain.c:1976-2006):
        to whom, then every purse pours in up to 9999. The command ends in
        dungeonmech (the turn passes)."""

        def _on_member(who: str) -> None:
            try:
                idx = int(who.strip()) - 1
            except ValueError:
                idx = -1
            if 0 <= idx < len(self.party.members):
                self.party.pool_gold(idx)
            self._consume_turn()

        self.text_log.prompt(
            "JOIN GOLD> To party member? (1-4):", callback=_on_member,
            single_char=True, on_cancel=self._consume_turn,
        )

    def _negate_time(self) -> None:
        """LairWare NegateTime (UltimaDngn.c:147; UltimaMain.c:2122-2139):
        whose powder; that member spends one and time stops for 10 turns.
        Nothing in a dungeon waits on stopped time."""
        from py_exodus.aura import AuraType

        def _spent(_member) -> None:
            self.text_log.add_message("Stop time with a powder!")
            self.party.aura.set(AuraType.QUICKNESS, 10)

        prompt_whose_item(
            self.text_log, self.party, "NEGATE TIME> Whose powder? (1-4):", "powder",
            _spent, turn_callback=self._consume_turn,
        )

    def _peer_gem(self) -> None:
        """LairWare dPeer (UltimaDngn.c:440-454): whose gem (message 75); a
        key outside 1-4 ends the command; a member with none gets "None
        left!" (67) and keeps everything; otherwise that member spends one
        and DrawMiniDng(0) shows the level.  Like every dungeon command it
        ends in dungeonmech (UltimaDngn.c:149, 161, 183), so the turn passes
        in all three cases, after the map when there is one.

        The PEER cheat (debug.CHEATS.free_peer) shows the map at once: no
        question, no gem."""

        def _spent(_member) -> None:
            self._gem_turn_pending = True
            self._open_gem_view()

        def _turn() -> None:
            if not self._gem_turn_pending:
                self._consume_turn()

        if debug.CHEATS.free_peer:
            _spent(None)
            return
        prompt_whose_item(
            self.text_log, self.party, "PEER> Whose gem? (1-4):", "gems",
            _spent, turn_callback=_turn,
        )

    def _open_gem_view(self) -> None:
        """Show the level map (dPeer, or Vieda: UltimaSpellCombat.c:322-327,
        ``if (Party[3] == 1) DrawMiniDng(0)``).  It owns the input."""
        self.gem_view_active = True
        self._gem_view_time = 0.0

    def _close_gem_view(self) -> None:
        self.gem_view_active = False
        if self._gem_turn_pending:
            self._gem_turn_pending = False
            self._consume_turn()
        self._run_fixture()

    def _prompt_yell(self) -> None:
        """LairWare Yell(0) (UltimaDngn.c:158; UltimaMain.c:2544-2550): a
        yelled word is an Other command; EVOCARE finds no serpent here."""

        def _on_member(who: str) -> None:
            try:
                idx = int(who.strip()) - 1
            except ValueError:
                idx = -1
            if not 0 <= idx < len(self.party.members):
                self.text_log.add_message("Nobody selected!")
                self._consume_turn()
                return

            def _on_word(word: str) -> None:
                if word.strip().upper() == "EVOCARE":
                    self.text_log.add_message("No effect.")
                else:
                    self._run_other(word)
                self._consume_turn()

            self.text_log.prompt("Yell what? ", callback=_on_word, on_cancel=self._consume_turn)

        self.text_log.prompt(
            "YELL> Which party member? (1-4):", callback=_on_member,
            single_char=True, on_cancel=self._consume_turn,
        )

    def _consume_turn(self) -> None:
        """Java DungeonScreen.finishTurn (DungeonScreen.java:1124) — the
        keyUp tail for keys without an early return. The encounter roll can
        raise a fight here too."""
        evt = self.state._tick_turn()
        if evt is not None:
            self._process_event(evt)
        self.check_party_death()

    def _process_event(self, evt: DungeonEvent) -> None:
        # Task 2 death flow: pit traps, fountains, and marks apply
        # damage before the event surfaces — a wiped party routes here
        # (Java GameScreen.java:433-446 partyDeath → start screen).
        if self.check_party_death():
            return

        if evt.message:
            self.text_log.add_message(evt.message)

        if self.audio is not None:
            if evt.type == DungeonEventType.BLOCKED:
                self.audio.play_sfx("blocked")
            elif evt.type in (DungeonEventType.MOVED, DungeonEventType.TURNED):
                self.audio.play_sfx("walk_normal")
            elif evt.type in (DungeonEventType.LADDER_UP, DungeonEventType.LADDER_DOWN):
                self.audio.play_sfx("trigger")
            elif evt.type == DungeonEventType.MARK:
                self.audio.play_sfx("lightning") or self.audio.play_sfx("magic")
            elif evt.type == DungeonEventType.FOUNTAIN:
                self.audio.play_sfx("magic")
            elif evt.type == DungeonEventType.CHEST:
                self.audio.play_sfx("trigger")
            # Java checkTileAffects' own Sounds.play calls, keyed by the same
            # event types (DungeonScreen.java:1080-1097): WIND, BOOM, GIGGLE.
            elif evt.type == DungeonEventType.WIND_TRAP:
                self.audio.play_sfx("tornado")
            elif evt.type == DungeonEventType.PIT_TRAP:
                self.audio.play_sfx("boom")
            elif evt.type == DungeonEventType.GREMLINS:
                self.audio.play_sfx("giggle")

        if evt.type == DungeonEventType.EXIT_DUNGEON:
            # evt.message was already logged at line 329 when non-empty.
            if not evt.message:
                self.text_log.add_message("Leaving dungeon...")
            self.exit_screen()
        elif evt.type == DungeonEventType.COMBAT:
            c_name = "skeleton"
            if evt.creature is not None:
                if hasattr(evt.creature, "tile"):
                    c_name = evt.creature.tile
                elif hasattr(evt.creature, "name"):
                    c_name = evt.creature.name.lower()
            self._trigger_combat(c_name)

    def _get_chest(self) -> None:
        """Open a treasure chest on the party's own tile."""
        from py_exodus.world.map import DungeonTile

        def _on_who(who_str: str) -> None:
            try:
                idx = int(who_str.strip()) - 1
            except ValueError:
                idx = -1
            member = self.party.get_member(idx)
            if member is None:
                self.text_log.add_message("Invalid member #!")
            elif member.is_disabled():
                # LairWare GetChest (UltimaMain.c:1601-1604): CheckAlive
                # comes before the tile is looked at.
                self.text_log.add_message("Incapacitated!")
            else:
                self._finish_dungeon_chest(member)
            self.check_party_death()
            # GetChest then dungeonmech (UltimaDngn.c:140, 161, 183-209): one
            # turn tick after the chest, answered or not.
            self._consume_turn()

        self.text_log.prompt(
            "Who gets the chest? (1-4): ", callback=_on_who, single_char=True,
            on_cancel=self._consume_turn,
        )

    def _finish_dungeon_chest(self, member) -> None:
        """Open the chest on the party's own tile through the Task 1 pipeline."""
        from py_exodus.world.chests import open_chest
        from py_exodus.world.map import DungeonTile

        x, y, z = self.state.x, self.state.y, self.state.z
        if self.dungeon_map.get_tile(x, y, z) != DungeonTile.CHEST:
            self.text_log.add_message("Not Here!")
            return

        self.dungeon_map.set_tile(x, y, z, DungeonTile.NOTHING)
        # Task 2 death flow: a chest trap (gas) can leave the whole party
        # dead; route game over (Java GameScreen.java:444-446 partyDeath
        # → start screen). The chests pipeline does not currently raise —
        # the try/except is future-proofing for later tasks routing it
        # through PartyMember.apply_damage; the post-check covers both.
        try:
            for line in open_chest(self.party, member, dungeon=True):
                self.text_log.add_message(line)
        except PartyDeathException:
            pass

    def _trigger_combat(self, creature_name: str) -> None:
        """Launch combat screen from dungeon encounter (LairWare dungeonmech,
        UltimaDngn.c:205-207: the chest is already on the tile)."""
        if self.asset_mgr is None:
            return

        try:
            from py_exodus.screens.combat_screen import CombatScreen
            from py_exodus.world.loader import MapLoader

            loader = MapLoader(self.asset_mgr)
            # Brick floor combat map (map ID 35)
            c_map = loader.load_conflict_map("cnflct_c.json")
            combat_scr = CombatScreen(
                party=self.party,
                combat_map=c_map,
                creature_tile=creature_name,
                asset_mgr=self.asset_mgr,
                audio=self.audio,
                return_screen=self,
                manager=self.manager,
                # Dungeon battle context (Java DungeonScreen.contextMap): the
                # dungeon's own map id — never Maps.EXODUS, but the arena must
                # not fall back to the party's stale last-overworld map id.
                context_map_id=self.map_id,
            )
            if self.manager is not None:
                self.manager.push_screen(combat_scr)
            else:
                self.next_screen = combat_scr
                self.is_finished = True
        except Exception:
            pass

    def end_combat(self, is_won: bool) -> None:
        """Nothing to settle: LairWare put the chest on the party's tile
        before the fight (UltimaDngn.c:206-207), whatever its end."""

    def _use_torch(self) -> None:
        """LairWare Ignite (UltimaMain.c:1955-1974): "Whose torch?"; that
        member burns one ("None left!" when empty; no CheckAlive) and the
        light is a fresh 255, lit or not (I never puts a torch out). The
        command ends in dungeonmech (UltimaDngn.c:142, 183-193), which burns
        one unit at once."""

        def _spent(_member) -> None:
            # User rule 2026-11-25 (P-18): light never shortens.
            self.state.torchtime = max(self.state.torchtime, 255)

        prompt_whose_item(
            self.text_log, self.party, "IGNITE> Whose torch? (1-4):", "torches",
            _spent, turn_callback=self._consume_turn,
        )

    def _toggle_music(self) -> None:
        """Java DungeonScreen.java:1013-1023 Keys.V — toggle music; the key
        falls through to finishTurn, so it consumes a turn."""
        if self.audio is not None:
            self.audio.enabled = not self.audio.enabled
            if self.audio.enabled:
                self.audio.play_music("dungeon")
            else:
                self.audio.stop_music()
        self._consume_turn()

    def exit_screen(self) -> None:
        # LairWare Routine6E6B (UltimaMisc.c:1336): ``Party[3] = 0; // back
        # to surface`` before the save; the ladder and Sequitu both end here.
        self.party.dungeon_level = 0
        super().exit_screen()
        # LairWare Routine6E6B (UltimaMisc.c:1336-1347): back on Sosaria,
        # classic AutoSave writes roster, party and Sosaria.
        self.party.run_autosave_hook()

    def _cast_spell(self) -> None:
        from py_exodus.combat.magic import prompt_cast_party
        prompt_cast_party(
            self.text_log,
            self.party,
            world_map=self.state,
            audio=self.audio,
            exit_callback=self.exit_screen,
            view_callback=self._open_gem_view,
        )

    def update(self, dt: float) -> None:
        """LairWare DungeonStart (UltimaDngn.c:55, 110-121)::

            #define PASSTIME 360          // 6 seconds
            nextPassTime = TickCount() + PASSTIME;
            ...
            if (TickCount() < nextPassTime) goto dungkey;
            gKeyPress = ' ';

        Six seconds of game time at the dungeon's command prompt with no key
        pass the turn as Space would. DoAutoHeal (zp[0xD1] == -2000) is not
        ported (user ruling). Prompts, Ztats and the level map never pass;
        autoplay holds it (realtime.autoplay_on)."""
        from py_exodus.world import realtime

        if self.gem_view_active:
            self._gem_view_time += max(0.0, dt)  # the party box blinks
        waiting = (
            not self.text_log.is_waiting_for_input
            and self.stats_panel.inspect_index is None
            and not self.gem_view_active
            and self._picture is None
            and not self.is_finished
            and self.party.is_anyone_alive()
            and not realtime.autoplay_on(self)
        )
        if not waiting:
            self._idle_time = 0.0
            return
        self._idle_time += max(0.0, dt)
        if self._idle_time + 1e-9 >= realtime.DUNGEON_PASS_SECONDS:
            self.handle_event(realtime.space_event())

    def _render_peer(self, surface: pygame.Surface, pane: int) -> None:
        """The level map over the view pane (LairWare DrawMiniDng(0), see
        py_exodus/ui/gem_view.py); the party panel and log stay up."""
        from py_exodus.ui.gem_view import marker_visible, render_dungeon_gem_view

        render_dungeon_gem_view(
            surface,
            pygame.Rect(0, 0, pane, pane),
            self.state.dmap,
            self.state.z,
            (self.state.x, self.state.y),
            marker_on=marker_visible(int(self._gem_view_time / 0.2)),
        )

    def render(self, surface: pygame.Surface) -> None:
        surface.fill(EGA_BLACK)
        w, h = surface.get_width(), surface.get_height()
        scale = 3 if w >= 640 else 1
        v_size = 176 * scale

        # The light rule: a lit torch (or the XRAY cheat), else pitch black.
        torch_lit = self.state.is_torch_on or debug.CHEATS.xray

        # The view is drawn at the original's 176x176 and enlarged.
        view = pygame.Surface((176, 176))
        self.camera.render_view(
            view,
            dmap=self.state.dmap,
            x=self.state.x,
            y=self.state.y,
            z=self.state.z,
            dir=self.state.dir,
            torch_lit=torch_lit,
            closeup=self._picture is not None,
        )
        if scale > 1:
            view = pygame.transform.scale(view, (v_size, v_size))
        surface.blit(view, (0, 0))

        font = get_hud_font(size=16 if scale > 1 else 10)
        status_line = f"LVL: {self.state.z + 1}  DIR: {self.state.dir.name}"
        stat_surf = font.render(status_line, True, EGA_YELLOW)
        surface.blit(stat_surf, (8, 6) if scale > 1 else (4, 4))

        # Right sidebar (party stats) and the text log under the view.
        self._render_stats_panel(
            surface,
            pygame.Rect(v_size, 0, w - v_size, h),
        )
        self.text_log.render(
            surface,
            rect=pygame.Rect(0, v_size, v_size, h - v_size if scale > 1 else max(24, h - 176)),
            draw_border=True,
        )
        if self.gem_view_active:
            self._render_peer(surface, v_size)
        self._render_ztats(surface, v_size)
