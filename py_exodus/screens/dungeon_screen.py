"""Dungeon exploration screen with 3D wireframe corridors, HUD, and combat triggers."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pygame

from py_exodus import debug
from py_exodus.assets import MAP_ID_TO_LABEL, MAP_NAME_TO_ID
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
    prompt_modify_order,
    prompt_ready_weapon,
    prompt_wear_armor,
)
from py_exodus.ui.stats_panel import StatsPanel
from py_exodus.ui.text_log import (
    EGA_BLACK,
    EGA_BRIGHT_CYAN,
    EGA_BRIGHT_RED,
    EGA_DARK_GRAY,
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


class DungeonScreen(BaseScreen):
    """First-person 3D wireframe dungeon navigation screen."""

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
        start_dir: Direction = Direction.NORTH,
        **kwargs: Any,
    ) -> None:
        super().__init__(return_screen=return_screen, **kwargs)
        self.party = party
        self.asset_mgr = asset_mgr
        self.audio = audio
        self.map_id = map_id

        # Load map if not provided
        was_injected = dungeon_map is not None
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
        self.camera = DungeonCamera(viewport_size=176)
        self.stats_panel = StatsPanel(asset_mgr=self.asset_mgr)
        self.text_log = TextLog(max_lines=5, wrap_width=28)
        # Java DungeonScreen.java:79-80 — the minimap shows by default and P
        # toggles it.
        self.show_minimap = True

        # Java DungeonScreen.currentEncounter (DungeonScreen.java:737): the
        # wandering creature that raised the current battle, cleared by
        # endCombat.
        self.current_encounter = None

        raw_id = getattr(self.dungeon_map, "id", None)
        if not was_injected and raw_id is None:
            raw_id = self.map_id
        lookup_id: int | None = None
        if raw_id is not None:
            try:
                lookup_id = int(raw_id)
            except (TypeError, ValueError):
                lookup_id = MAP_NAME_TO_ID.get(str(raw_id).upper())
        label = (
            MAP_ID_TO_LABEL.get(lookup_id)
            if lookup_id is not None and lookup_id != 0
            else None
        ) or getattr(self.dungeon_map, "name", "Dungeon")
        self.text_log.add_message(f"Entering {label}!")
        self.text_log.add_message("Level 1. Darkness surrounds thee.")

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
        if self.audio is not None:
            self.audio.play_music("dungeon")

    def handle_event(self, event: pygame.event.Event) -> None:
        # Mouse wheel scrolls the shared text log back through history
        # (Java LogScrollPane affordance; wheel is never a dungeon command).
        if event.type == pygame.MOUSEWHEEL:
            self.text_log.handle_wheel(event)
            return

        if event.type != pygame.KEYDOWN:
            return

        if self.text_log.is_waiting_for_input:
            self.text_log.handle_event(event)
            return

        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): debug cheat
        # harness (GBC cheat.c:768-825 docheat) — F10 opens the cheat menu in
        # --debug mode only; non-debug F10 stays inert.
        if debug.DEBUG_MODE and event.key == pygame.K_F10:
            debug.open_cheat_menu(self.text_log, self.party)
            return

        # PageUp/PageDown always scroll the text log back (arrow keys scroll
        # only inside the log's own prompt handling, when they cannot act as
        # direction/command answers).
        if self.text_log.handle_scroll_key(event.key):
            return

        # Movement and navigation keys: Arrow keys and Keypad ONLY (no WASD)
        # Java DungeonScreen.java:859-957 — LEFT/RIGHT rotate the camera in
        # place (no turn consumed); UP steps forward; DOWN steps one square
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
            # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): ladders consume
            # a turn (GBC ult3.c:1388-1429; LW free-action ladders disagree,
            # no LW+NES agreement — GBC retained). Java DungeonScreen.java:
            # 959-971 returned before finishTurn.
            evt = self.state.klimb_up()
            self._process_event(evt)
        elif event.key == pygame.K_d:
            # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): ladders consume
            # a turn (GBC ult3.c:1388-1429; LW free-action ladders disagree,
            # no LW+NES agreement — GBC retained). Java DungeonScreen.java:
            # 973-981 returned before finishTurn.
            evt = self.state.klimb_down()
            self._process_event(evt)
        elif event.key == pygame.K_i:
            self._use_torch()
        elif event.key == pygame.K_p:
            # Java DungeonScreen.java:79-80 + 1012-1015 — P toggles the
            # minimap and falls through the keyUp tail (turn consumed).
            self.show_minimap = not self.show_minimap
            self._consume_turn()
        elif event.key == pygame.K_v:
            # Java DungeonScreen.java:1013-1023 — V toggles music and falls
            # through the keyUp tail (turn consumed).
            self._toggle_music()
        elif event.key == pygame.K_m:
            # Java DungeonScreen.java:1024-1031 — M routes to
            # NewOrderInputAdapter, which does not finishTurn from a dungeon.
            # Java's log keeps the typo "exhange #:" (DungeonScreen.java:1028).
            prompt_modify_order(self.text_log, self.party, exchange_label="exhange #:")
        elif event.key == pygame.K_r:
            # Java DungeonScreen.java:1011-1013 — G/R/W/C/S fall through to
            # finishTurn at the press, then route to the member selection flow.
            self._consume_turn()
            prompt_ready_weapon(
                self.text_log, self.party, self.asset_mgr, turn_callback=self._consume_turn
            )
        elif event.key == pygame.K_w:
            self._consume_turn()
            prompt_wear_armor(
                self.text_log, self.party, self.asset_mgr, turn_callback=self._consume_turn
            )
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
        elif event.key == pygame.K_s:
            self._consume_turn()
            self._search()
        elif event.key == pygame.K_g:
            self._consume_turn()
            self._get_chest()
        elif event.key == pygame.K_z:
            # Java DungeonScreen.java:1033-1044 — Z cycles the zstats view and
            # returns before finishTurn (no turn consumed, unlike the
            # overworld's Z).
            self._toggle_zstats()
        else:
            # Java DungeonScreen.java:1045-1049 + 1049-1050 — any key without
            # a handler logs "Pass" and falls through to finishTurn.
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

    def _prompt_other(self) -> None:
        """Other command from a dungeon (GBC menucmd3.c:1019-1236 subset).

        USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): GBC's bribe/steal/
        dig are OUTSIDE-only, so the dungeon refuses them with the GBC
        noeffectdat message; pray/search/score delegate to the shared
        py_exodus.special_commands flows.
        """
        def _on_other(cmd: str) -> None:
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
            elif c == "SCORE":
                self.text_log.add_message(special_commands.do_score(self.party))
            else:
                self.text_log.add_message(f"'{c}': Nothing happened.")

        self.text_log.prompt("Other Command? ", callback=_on_other)

    def _consume_turn(self) -> None:
        """Java DungeonScreen.finishTurn (DungeonScreen.java:1124) — the
        keyUp tail for keys without an early return. A wandering creature
        reaching the avatar raises the battle here too."""
        evt = self.state._tick_turn()
        if evt is not None:
            self._process_event(evt)
        self.check_party_death()

    def _toggle_zstats(self) -> None:
        """Cycle Ztats inspect mode through party members."""
        current = self.stats_panel.inspect_index
        member_count = len(self.party.members)
        if member_count == 0:
            return
        if current is None:
            self.stats_panel.inspect_index = 0
        elif current + 1 < member_count:
            self.stats_panel.inspect_index = current + 1
        else:
            self.stats_panel.inspect_index = None

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
            self._trigger_combat(c_name, encounter=evt.wandering)

    def _search(self) -> None:
        """Search dungeon tile for fountains, marks, or chests."""
        from py_exodus.world.map import DungeonTile

        tile = self.state.current_tile
        fountains = (
            DungeonTile.FOUNTAIN_PLAIN,
            DungeonTile.FOUNTAIN_HEAL,
            DungeonTile.FOUNTAIN_ACID,
            DungeonTile.FOUNTAIN_CURE,
            DungeonTile.FOUNTAIN_POISON,
        )
        marks = (
            DungeonTile.MARK,
            DungeonTile.MARK_KINGS,
            DungeonTile.MARK_FIRE,
            DungeonTile.MARK_SNAKE,
            DungeonTile.MARK_FORCE,
        )

        if tile in fountains:
            prompt_msg = "You find a Fountain. Who drinks? (1-4): "
            action = self.state.drink_fountain
        elif tile in marks:
            prompt_msg = "You find a mystical Mark. Who touches? (1-4): "
            action = self.state.touch_mark
        elif tile == DungeonTile.CHEST:
            prompt_msg = "Who gets the chest? (1-4): "
            action = lambda idx: self.state.open_chest(idx, disarm=False)
        else:
            prompt_msg = "Who searches? (1-4): "
            action = None

        def _on_who(who_str: str) -> None:
            try:
                idx = int(who_str.strip()) - 1
            except ValueError:
                idx = 0

            if not (0 <= idx < len(self.party.members)):
                self.text_log.add_message("Invalid member #!")
            elif action is not None:
                try:
                    evt = action(idx)
                except PartyDeathException:
                    # Java: catch → partyDeath(); the event's post-check routes it
                    evt = None
                if evt is not None:
                    self._process_event(evt)
                self.check_party_death()
            else:
                self.text_log.add_message("Search: Thou searchest the damp corridor... Nothing here!")

            # Java: dungeon S is routed through the G/R/W/C/S fall-through
            # branch (DungeonScreen.java:1011-1013) and every sip keypress
            # ends in the sip tail finishTurn — valid or not. A wandering
            # creature reaching the avatar in that tail raises the battle.
            tick_evt = self.state._tick_turn()
            if tick_evt is not None:
                self._process_event(tick_evt)
            self.check_party_death()

        self.text_log.prompt(prompt_msg, callback=_on_who, single_char=True)

    def _get_chest(self) -> None:
        """Open a treasure chest on the party's own tile."""
        from py_exodus.world.map import DungeonTile

        def _on_who(who_str: str) -> None:
            tick_evt = self.state._tick_turn()  # Java routes G through finishTurn
            try:
                idx = int(who_str.strip()) - 1
            except ValueError:
                idx = -1
            member = self.party.get_member(idx)
            if member is None:
                self.text_log.add_message("Invalid member #!")
            else:
                self._finish_dungeon_chest(member)
            if tick_evt is not None:
                self._process_event(tick_evt)
            self.check_party_death()

        self.text_log.prompt("Who gets the chest? (1-4): ", callback=_on_who, single_char=True)

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

    def _trigger_combat(self, creature_name: str, encounter=None) -> None:
        """Launch combat screen from dungeon encounter.

        ``encounter`` is the wandering creature instance that raised the
        battle (Java DungeonScreen.battleWandering keeps it in
        ``currentEncounter`` until endCombat removes it and drops any chest).
        """
        self.current_encounter = encounter
        if self.asset_mgr is None:
            return

        try:
            from py_exodus.screens.combat_screen import CombatScreen
            from py_exodus.world.loader import MapLoader

            loader = MapLoader(self.asset_mgr)
            # Brick floor combat map (map ID 35)
            c_map = loader.load_conflict_map("cnflct_b.json")
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
        """Java DungeonScreen.endCombat (DungeonScreen.java:740-769).

        A victory leaves the encounter creature's chest on the avatar's tile
        — only onto a NOTHING tile, and only when the creature is not
        `nochest`. The encounter creature is then removed from the dungeon
        level unconditionally, win or loss (dngMap.removeCreature), so the
        battle cannot re-trigger on every following tick.
        """
        from py_exodus.world.map import DungeonTile

        encounter = self.current_encounter
        if encounter is not None:
            if (
                is_won
                and not encounter.creature.no_chest
                and self.dungeon_map.get_tile(self.state.x, self.state.y, self.state.z)
                == DungeonTile.NOTHING
            ):
                self.dungeon_map.set_tile(
                    self.state.x, self.state.y, self.state.z, DungeonTile.CHEST
                )
            self.state.wandering_creatures = [
                wc for wc in self.state.wandering_creatures if wc is not encounter
            ]
            self.current_encounter = None

    def _use_torch(self) -> None:
        """Toggle the torch (Java DungeonScreen.java:988-1004 Keys.I).

        A lit torch press extinguishes it with no consumption; otherwise
        `DungeonState.ignite` burns the first member's torch and loads the
        GBC counter to 255 — USER-DIRECTED GBC-RULES DEVIATION (2026-11-14):
        finite torch durations (GBC dungfun2.c:1168-1191 doignite). With
        none owned the log prints "No Torches!". Every press falls through
        to finishTurn (which then burns one `torchtime` unit —
        dungfunc.c:719-734), so the keypress completes one round down.
        """
        if self.state.is_torch_on:
            self.state.torchtime = 0
        elif not self.state.ignite():
            self.text_log.add_message("No Torches!")
        self._consume_turn()

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

    def _cast_spell(self) -> None:
        from py_exodus.combat.magic import prompt_cast_party
        prompt_cast_party(
            self.text_log,
            self.party,
            world_map=self.state,
            audio=self.audio,
            exit_callback=self.exit_screen,
        )

    def update(self, dt: float) -> None:
        pass

    def _render_minimap(self, target: pygame.Surface) -> None:
        """Draw the current dungeon level as a small top-down chart.

        Java truth: DungeonScreen.java:79-80 keeps ``showMiniMap`` True by
        default and the Keys.P handler (DungeonScreen.java:1012-1015)
        toggles it — the party explores with a level plan overlaid on the
        viewport and presses P to hide it.
        """
        from py_exodus.world.map import DungeonTile

        cell = 4
        dmap = self.state.dmap
        offset_x = target.get_width() - dmap.width * cell - 4
        offset_y = 20
        for gy in range(dmap.height):
            for gx in range(dmap.width):
                tile = dmap.get_tile(gx, gy, self.state.z)
                if tile == DungeonTile.WALL:
                    color = EGA_BRIGHT_CYAN
                else:
                    color = EGA_DARK_GRAY
                target.fill(color, (offset_x + gx * cell, offset_y + gy * cell, cell - 1, cell - 1))
        # Party position dot
        px = offset_x + self.state.x * cell
        py = offset_y + self.state.y * cell
        target.fill(EGA_BRIGHT_RED, (px, py, cell - 1, cell - 1))
        # Wandering-creature dots: one marker per creature on the level so
        # the dungeon monsters are visible next to the party dot.
        for wc in self.state.wandering_creatures:
            if wc.level != self.state.z:
                continue
            cx = offset_x + wc.x * cell
            cy = offset_y + wc.y * cell
            target.fill(EGA_YELLOW, (cx, cy, cell - 1, cell - 1))

    def render(self, surface: pygame.Surface) -> None:
        surface.fill(EGA_BLACK)
        w, h = surface.get_width(), surface.get_height()
        scale = 3 if w >= 640 else 1
        v_size = 176 * scale

        torch_lit = self.state.is_torch_on

        if scale > 1:
            temp_v = pygame.Surface((176, 176))
            self.camera.render_wireframe(
                temp_v,
                dmap=self.state.dmap,
                x=self.state.x,
                y=self.state.y,
                z=self.state.z,
                dir=self.state.dir,
                torch_lit=torch_lit,
                creatures=self.state.wandering_creatures,
            )

            font = get_hud_font(size=10)
            status_line = f"LVL: {self.state.z + 1}  DIR: {self.state.dir.name}"
            stat_surf = font.render(status_line, True, EGA_YELLOW)
            temp_v.blit(stat_surf, (4, 4))

            if self.show_minimap:
                self._render_minimap(temp_v)

            scaled_v = pygame.transform.scale(temp_v, (v_size, v_size))
            surface.blit(scaled_v, (0, 0))

            # Right Sidebar (Party Stats) at native high resolution
            self._render_stats_panel(
                surface,
                pygame.Rect(v_size, 0, w - v_size, h),
            )

            # Bottom HUD Text Log at native resolution
            self.text_log.render(
                surface,
                rect=pygame.Rect(0, v_size, v_size, h - v_size),
                draw_border=True,
            )
        else:
            self.camera.render_wireframe(
                surface,
                dmap=self.state.dmap,
                x=self.state.x,
                y=self.state.y,
                z=self.state.z,
                dir=self.state.dir,
                torch_lit=torch_lit,
                creatures=self.state.wandering_creatures,
            )

            font = get_hud_font(size=10)
            status_line = f"LVL: {self.state.z + 1}  DIR: {self.state.dir.name}"
            stat_surf = font.render(status_line, True, EGA_YELLOW)
            surface.blit(stat_surf, (4, 4))

            if self.show_minimap:
                self._render_minimap(surface)

            self._render_stats_panel(
                surface,
                pygame.Rect(176, 0, w - 176, h),
            )

            log_h = max(24, h - 176)
            self.text_log.render(
                surface,
                rect=pygame.Rect(0, 176, 176, log_h),
                draw_border=True,
            )
