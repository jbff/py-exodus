"""Overworld exploration screen for Sosaria and Ambrosia."""
from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

import pygame

from py_exodus.aura import AuraType
from py_exodus.combat.magic import prompt_cast_party
from py_exodus.constants import (
    BASE_HEIGHT,
    BASE_WIDTH,
    TILE_SIZE,
    Direction,
    MapType,
    Status,
    Transport,
)
from py_exodus.entities.party import PartyDeathException
from py_exodus.screens.base import BaseScreen
from py_exodus.screens.member_prompts import (
    prompt_modify_order,
    prompt_ready_weapon,
    prompt_wear_armor,
)
from py_exodus.screens.final import (
    apply_exodus_card_tiles,
    prompt_insert_card,
)
from py_exodus.ui.renderer import WorldRenderer, can_move_to
from py_exodus.ui.stats_panel import StatsPanel
from py_exodus.ui.text_log import (
    EGA_BLACK,
    EGA_BRIGHT_CYAN,
    EGA_BRIGHT_GREEN,
    EGA_BRIGHT_RED,
    EGA_DARK_GRAY,
    EGA_LIGHT_GRAY,
    EGA_WHITE,
    EGA_YELLOW,
    TextLog,
    get_hud_font,
)
from py_exodus.world import doors as door_module
from py_exodus.world import portal_entry
from py_exodus.world import search as search_module
from py_exodus.world import tile_effects

if TYPE_CHECKING:
    from py_exodus.assets import AssetManager
    from py_exodus.audio import AudioManager
    from py_exodus.entities.party import Party
    from py_exodus.world.map import GameMap


class OverworldScreen(BaseScreen):
    """Exploration screen for the Sosaria world map and Ambrosia continent."""

    def __init__(
        self,
        party: Party,
        map_id: int | str = 0,
        asset_mgr: AssetManager | None = None,
        audio: AudioManager | None = None,
        return_screen: BaseScreen | None = None,
        random_encounters: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(return_screen=return_screen, **kwargs)
        self.party = party
        self.map_id = map_id
        self.asset_mgr = asset_mgr
        self.audio = audio
        self.random_encounters_enabled = random_encounters

        self.game_map: GameMap | None = None
        # Wandering overland creatures visible on Sosaria (declared before the
        # first map load so _load_world_map can purge stale fixtures)
        self.creatures: list[dict[str, Any]] = []
        self._load_world_map()

        self.anim_frame = 0
        self.anim_timer = 0.0
        self.moon_timer = 0.0
        self.moon_phase = 0

        self.world_renderer = (
            WorldRenderer(asset_mgr) if asset_mgr is not None else None
        )
        self.stats_panel = StatsPanel()
        self.text_log = TextLog(max_lines=5, wrap_width=28)

        # Heading / facing direction (for broadside cannon checks)
        self.heading: Direction = Direction.NORTH

        if self.random_encounters_enabled:
            for _ in range(3):
                self._spawn_wandering_creature()

        map_name = getattr(self.game_map, "name", "Sosaria")
        self.text_log.add_message(f"Entering the realm of {map_name}...")
        self.text_log.add_message(f"Wind blows {self.party.wind_direction.name}.")

    @property
    def trammel_phase(self) -> int:
        return min(7, self.moon_phase // 3)

    @property
    def felucca_phase(self) -> int:
        return self.moon_phase % 8

    @property
    def moons(self) -> tuple[int, int]:
        return (self.trammel_phase, self.felucca_phase)

    def _load_world_map(self) -> None:
        # A map switch drops every standing creature (wanderer or whirlpool
        # fixture).
        self.creatures.clear()
        if self.asset_mgr is None:
            return
        try:
            from py_exodus.world.loader import MapLoader

            loader = MapLoader(self.asset_mgr)
            loaded = loader.load_map(self.map_id)
            if hasattr(loaded, "width"):
                self.game_map = loaded
        except Exception:
            pass

        # Java GameScreen.java:111-121 — the two Sosaria whirlpools are added
        # manually on the SOSARIA map each time it is prepared (they never
        # spawn automatically and never wander); re-seeding HERE (not in
        # __init__) keeps the engulf route alive after Ambrosia round trips,
        # which reload this screen in place with map_id 0.
        if str(self.map_id) == "0":
            for wx, wy in ((50, 13), (17, 48)):
                self.creatures.append({
                    "name": "Whirlpool",
                    "tile_name": "whirlpool",
                    "tile": "whirlpool",
                    "x": wx,
                    "y": wy,
                    "wontattack": True,
                })

    def on_enter(self) -> None:
        super().on_enter()
        self._play_overworld_music()
        # Restore cleared machine panels from exodusCardsStatus (GameScreen.java:299-311)
        apply_exodus_card_tiles(
            self.game_map, self.asset_mgr, getattr(self.party, "exodus_cards_status", 0)
        )
        # Purge any creature at the party's tile to prevent combat re-trigger loops
        self.creatures = [
            c for c in self.creatures
            if not (c.get("x") == self.party.x and c.get("y") == self.party.y)
        ]

    def _play_overworld_music(self) -> None:
        if self.audio is None:
            return
        if str(self.map_id) in ("13", "ambrosia"):
            self.audio.play_music("dungeon")
        else:
            self.audio.play_music("wander")

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return

        if self.text_log.is_waiting_for_input:
            self.text_log.handle_event(event)
            return

        # Directional Movement: Arrow keys and Keypad ONLY (no WASD)
        if event.key in (pygame.K_UP, pygame.K_KP8):
            self._move_avatar(Direction.NORTH)
        elif event.key in (pygame.K_DOWN, pygame.K_KP2):
            self._move_avatar(Direction.SOUTH)
        elif event.key in (pygame.K_LEFT, pygame.K_KP4):
            self._move_avatar(Direction.WEST)
        elif event.key in (pygame.K_RIGHT, pygame.K_KP6):
            self._move_avatar(Direction.EAST)
        elif event.key == pygame.K_SPACE:
            self._pass_turn()
        # Complete Ultima III Alphabetical Commands A-Z:
        elif event.key == pygame.K_a:
            self._prompt_attack_overworld()
        elif event.key == pygame.K_b:
            # Java GameScreen.java:578-580 — B runs board() and falls through
            # the keyUp tail, so every board attempt consumes a turn.
            self._board_transport()
            self._consume_pass_turn()
        elif event.key == pygame.K_c:
            self._prompt_cast()
        elif event.key == pygame.K_e:
            self._enter_portal()
        elif event.key == pygame.K_f:
            # Java GameScreen.java:531-536 — F is only the cannon prompt on a
            # ship; any other state reaches the keyUp tail SILENTLY (no
            # message) and still consumes a turn.
            if self.party.transport == Transport.SHIP:
                self._prompt_fire_cannons()
            else:
                self._consume_pass_turn()
        elif event.key == pygame.K_g:
            self._get_chest()
        elif event.key == pygame.K_h:
            self._prompt_hand_equipment()
        elif event.key == pygame.K_j:
            self._join_gold()
        elif event.key == pygame.K_l:
            self._open()
        elif event.key == pygame.K_m:
            self._prompt_modify_order()
        elif event.key == pygame.K_n:
            self._negate_time()
        elif event.key == pygame.K_o:
            self._prompt_other()
        elif event.key == pygame.K_p:
            self._peer_gem()
        elif event.key == pygame.K_q:
            self._save_game()
        elif event.key == pygame.K_r:
            self._prompt_ready_weapon()
        elif event.key == pygame.K_s:
            self._search()
        elif event.key == pygame.K_t:
            self._talk()
        elif event.key == pygame.K_u:
            self._unlock()
        elif event.key == pygame.K_v:
            self._toggle_volume()
        elif event.key == pygame.K_w:
            self._prompt_wear_armor()
        elif event.key == pygame.K_x:
            # Java GameScreen.java:584-596 — X has no early return; every
            # dismount press consumes a turn.
            self._exit_transport()
            self._consume_pass_turn()
        elif event.key == pygame.K_y:
            self._prompt_yell()
        elif event.key == pygame.K_z:
            self._toggle_zstats()
        else:
            # Java GameScreen.keyUp tail (GameScreen.java:628): every key that
            # has no explicit early return — including the unhandled D, I and
            # K — falls through to finishTurn(v.x, v.y) with no message.
            self._consume_pass_turn()

    def _consume_pass_turn(self) -> None:
        """Java GameScreen.keyUp tail (GameScreen.java:628): finishTurn on the
        party's tile, with no message. Used by the unhandled-key fall-through
        and by handled keys that Java lets reach the tail (Q, Z, H, P, N, V)."""
        self._finish_turn(self.game_map.get_tile(self.party.x, self.party.y) if self.game_map else None)
        self._update_creatures()

    def _pass_turn(self) -> None:
        """Pass turn in place without moving avatar.

        Java truth: ``GameScreen.java:624-628`` — the pass key ends the key
        handler with ``finishTurn(v.x, v.y)``, so passing consumes the turn
        and applies the rule effect of the party's tile exactly like a move.
        """
        self.text_log.add_message("Pass")  # Java GameScreen.java:626-627
        self._finish_turn(self.game_map.get_tile(self.party.x, self.party.y) if self.game_map else None)
        self._update_creatures()

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

        if self.stats_panel.inspect_index is not None:
            m = self.party.members[self.stats_panel.inspect_index]
            self.text_log.add_message(f"Zstats: {m.name} ({m.profession.name})")
            cur_w = m.weapon.name if hasattr(m.weapon, "name") else str(m.weapon)
            cur_a = m.armor.name if hasattr(m.armor, "name") else str(m.armor)
            self.text_log.add_message(f"Readied: {cur_w}  Worn: {cur_a}")
            wpn_list = [f"{wt.name}:{cnt}" for wt, cnt in m.weapons.items() if cnt > 0]
            arm_list = [f"{at.name}:{cnt}" for at, cnt in m.armors.items() if cnt > 0]
            if wpn_list:
                self.text_log.add_message("Weapons: " + ", ".join(wpn_list))
            if arm_list:
                self.text_log.add_message("Armors: " + ", ".join(arm_list))
        else:
            self.text_log.add_message("Zstats: Normal view")
        # Java GameScreen.java:564-572 — Z has no early return; consumes a turn.
        self._consume_pass_turn()

    def _prompt_cast(self) -> None:
        """Prompt active member to cast an overland spell."""
        prompt_cast_party(self.text_log, self.party, world_map=self.game_map, audio=self.audio)

    def _get_chest(self) -> None:
        """GET: pick the opening member, then check ONLY the party's own tile
        (fix round 2 — final ruling).

        Java truth: ``exodus/SecondaryInputProcessor.java:126-160, 308-318`` —
        x/y is a per-event local copy; the G branch fires only when a member
        digit follows G, and on that event x/y are the unshifted
        ``currentX/currentY`` (arrows never reach ``getChest``). So the chest
        under the party's feet IS the openable chest — no direction step, no
        adjacency scan — and ``GameScreen.getChest`` (GameScreen.java:
        1036-1074) falls back to the chest *tile* at the same coordinates.
        Non-digit input logs NOTHING (Java falls through silently); the
        keydown still consumes a turn (SIP ``finishTurn`` at line 459, which
        passes the party's tile — so the tile-rule effect uses it too).
        """
        from py_exodus.assets import TileDef
        from py_exodus.world.chests import ChestNotFound, open_chest, take_chest_object

        def _on_who(who_str: str) -> None:
            member = self._parse_member(who_str)
            if member is None:
                # Non-digits fall through silently (Java), but the keydown
                # still consumes the turn at the party's tile (SIP:459).
                self._finish_turn(
                    self.game_map.get_tile(self.party.x, self.party.y)
                    if self.game_map else None
                )
                return

            px, py = self.party.x, self.party.y
            try:
                take_chest_object(self.party, px, py)
            except ChestNotFound:
                # Java getChest: a chest *tile* under the party is replaced
                # with floor (GameScreen.java:1069-1071).
                tile = self.game_map.get_tile(px, py) if self.game_map else None
                if tile is None or getattr(tile, "rule", "") != "chest":
                    self.text_log.add_message("Not Here!")
                    self._finish_turn(
                        self.game_map.get_tile(px, py) if self.game_map else None
                    )
                    return
                self.game_map.set_tile(px, py, TileDef(index=3, name="floor"))

            # Task 2 death flow: a chest trap (gas) can leave the whole party
            # dead; route game over (Java GameScreen.java:444-446 partyDeath
            # → start screen). The chests pipeline does not currently raise —
            # the try/except is future-proofing for later tasks routing it
            # through PartyMember.apply_damage; the post-check covers both.
            try:
                for line in open_chest(self.party, member):
                    self.text_log.add_message(line)
            except PartyDeathException:
                pass
            if self.check_party_death():
                return
            if self.audio is not None:
                self.audio.play_sfx("trigger")
            self._finish_turn(self.game_map.get_tile(px, py) if self.game_map else None)

        self.text_log.prompt("GET> Which party member? (1-4):", callback=_on_who, single_char=True)

    def _join_gold(self) -> None:
        """JOIN GOLD: prompt a member 1-4 and pool every purse into theirs.

        Java truth: ``exodus/SecondaryInputProcessor.java:271-277`` — the J key
        logs ``JOIN GOLD> To party member? (1-4)`` and calls
        ``Party.poolGold(index)`` (Party.java:88-97); nothing is logged.
        """
        self.text_log.prompt(
            "JOIN GOLD> To party member? (1-4):",
            callback=self._pool_to_member,
            single_char=True,
        )

    def _pool_to_member(self, who_str: str) -> None:
        member = self._parse_member(who_str)
        if member is None:
            return  # non-digits fall through silently (Java)
        self.party.pool_gold(self.party.members.index(member))

    def _peer_gem(self) -> None:
        """Peer into mystical gem to survey surroundings.

        Java truth: GameScreen.java:604-605 — P runs peerGem() and falls
        through the keyUp tail, so peer commands consume a turn even when no
        gem is owned.
        """
        if self.party.gems > 0:
            self.party.gems -= 1
            m_name = getattr(self.game_map, "name", "Sosaria")
            self.text_log.add_message(f"Gem vision: {m_name} at X={self.party.x}, Y={self.party.y}.")
        else:
            self.text_log.add_message("None owned!")
        self._consume_pass_turn()

    def _exit_transport(self) -> None:
        """Dismount horse or ship onto foot, persisting transport on map.

        Java truth: ``exodus/GameScreen.java:584-596`` — X while on a ship
        drops the frigate object on the tile and records it as
        ``Context.lastShip``, so re-boarding the same hull keeps its damage.
        """
        # Java GameScreen.java:584-596 — X is silent on foot (it only resets
        # the transport and sets the avatar anim); the keyUp tail still ticks.
        if self.party.transport == Transport.FOOT:
            return

        old_t = self.party.transport
        self.party.transport = Transport.FOOT
        if old_t == Transport.HORSE:
            self.party.dynamic_objects.append({"tile": "horse", "x": self.party.x, "y": self.party.y})
            self.text_log.add_message("Dismounted horse.")
        else:
            ship = {"tile": "frigate", "x": self.party.x, "y": self.party.y}
            self.party.dynamic_objects.append(ship)
            self.party.last_ship = ship
            self.text_log.add_message("Disembarked frigate.")

    def _board_transport(self) -> None:
        """Board the frigate or horse exactly on the party's tile (Java ``B``).

        Java truth: ``exodus/GameScreen.java:945-979`` ``board(x, y)`` —
        already mounted: "Board: Can't!"; a frigate object with
        ``cx == x && cy == y`` boards (a *fresh* one resets the hull to 50 via
        ``adjustShipHull(50)``), then a horse creature on the exact tile
        mounts, otherwise "Board What?". There is no auto-mounting and no
        Chebyshev-1 adjacency.
        """
        if self.party.transport != Transport.FOOT:
            self.text_log.add_message("Board: Can't!")
            return

        px, py = self.party.x, self.party.y

        # Frigate object on the party's exact tile
        for idx, obj in enumerate(self.party.dynamic_objects):
            tile = str(obj.get("tile", "")).lower()
            if tile in ("frigate", "ship") and obj.get("x") == px and obj.get("y") == py:
                self.party.dynamic_objects.pop(idx)
                self.party.transport = Transport.SHIP
                if self.party.last_ship is not obj:
                    # Fresh frigate: hull + 50 capped at 50 == reset to 50
                    # (Java adjustShipHull, Party.java:74-76).
                    self.party.adjust_ship_hull(50)
                self.party.last_ship = obj
                if self.audio is not None:
                    self.audio.play_sfx("trigger")
                self.text_log.add_message("Board Frigate!")
                return

        # Horse object on the party's exact tile
        for obj in self.party.dynamic_objects:
            if obj.get("x") == px and obj.get("y") == py:
                if str(obj.get("tile", "")).lower() == "horse":
                    self.party.dynamic_objects.remove(obj)
                    self.party.transport = Transport.HORSE
                    if self.audio is not None:
                        self.audio.play_sfx("trigger")
                    self.text_log.add_message("Mount Horse!")
                    return

        # Wandering horse creature on the party's exact tile
        # (Java: getCreatureAt(x, y) with tile name "horse")
        for c in self.creatures:
            if (
                c.get("tile_name") == "horse"
                and c.get("x") == px
                and c.get("y") == py
            ):
                self.creatures.remove(c)
                self.party.transport = Transport.HORSE
                if self.audio is not None:
                    self.audio.play_sfx("trigger")
                self.text_log.add_message("Mount Horse!")
                return

        self.text_log.add_message("Board What?")

    def _parse_member(self, who_str: str):
        """Resolve a 1-4 member prompt answer to a PartyMember (or None)."""
        try:
            idx = int(who_str.strip()) - 1
            return self.party.get_member(idx)
        except ValueError:
            return None

    def _open(self) -> None:
        """L = OPEN with a direction (Java SIP:212-219 + BaseMap.openDoor)."""
        self.text_log.prompt(
            "OPEN> Direction? (N,S,E,W):",
            callback=self._parse_and_open,
            single_char=True,
        )

    def _parse_and_open(self, d_str: str) -> None:
        d = Direction.from_name_or_key(d_str)
        if d is None:
            self.text_log.add_message("Invalid direction!")
            return
        if self.game_map is None:
            self.text_log.add_message("Can't!")
            return
        if door_module.open_door(self.game_map, self.party.x + d.dx, self.party.y + d.dy):
            self.text_log.add_message("Opened!")
        else:
            self.text_log.add_message("Can't!")

    def _prompt_hand_equipment(self) -> None:
        """Hand an unequipped weapon or armor item between party members.

        Java truth: GameScreen.java:574-576 — H opens HandDialog and falls
        through the keyUp tail, so it consumes a turn at the press.
        """
        self._consume_pass_turn()
        if len(self.party.members) < 2:
            self.text_log.add_message("Hand Equipment: Need at least 2 members!")
            return

        def _on_from(from_str: str) -> None:
            try:
                p1 = int(from_str.strip()) - 1
            except ValueError:
                self.text_log.add_message("Invalid member #!")
                return
            if not (0 <= p1 < len(self.party.members)):
                self.text_log.add_message("Invalid member #!")
                return

            def _on_to(to_str: str) -> None:
                try:
                    p2 = int(to_str.strip()) - 1
                except ValueError:
                    self.text_log.add_message("Invalid member #!")
                    return
                if not (0 <= p2 < len(self.party.members)) or p1 == p2:
                    self.text_log.add_message("Invalid recipient!")
                    return

                m1 = self.party.members[p1]
                m2 = self.party.members[p2]

                # Java HandDialog.java:114-146 — the ">" button transfers the
                # selected unequipped weapon or armor (count decrement /
                # increment); there is no gold transfer and an empty selection
                # only plays the BLOCKED sound.
                transferred = False
                for w, cnt in list(m1.weapons.items()):
                    if cnt > 0 and w != m1.weapon:
                        m1.weapons[w] -= 1
                        m2.weapons[w] = m2.weapons.get(w, 0) + 1
                        self.text_log.add_message(f"{m1.name} handed {w.name} to {m2.name}.")
                        transferred = True
                        break

                if not transferred:
                    for a, cnt in list(m1.armors.items()):
                        if cnt > 0 and a != m1.armor:
                            m1.armors[a] -= 1
                            m2.armors[a] = m2.armors.get(a, 0) + 1
                            self.text_log.add_message(f"{m1.name} handed {a.name} to {m2.name}.")
                            transferred = True
                            break
                    # No gold fallback: Java HandDialog transfers equipment
                    # only (HandDialog.java:114-146).

            self.text_log.prompt("To member #? (1-4): ", callback=_on_to, single_char=True)

        self.text_log.prompt("Hand Equipment: From member #? (1-4): ", callback=_on_from, single_char=True)

    def _prompt_modify_order(self) -> None:
        """Modify marching order of party (Java BaseScreen.java:165-204
        NewOrderInputAdapter — shared member_prompts flow)."""
        prompt_modify_order(self.text_log, self.party, turn_callback=self._consume_pass_turn)

    def _negate_time(self) -> None:
        """NEGATE TIME: consume the FIRST member's powder for a 6-turn
        QUICKNESS aura (Java GameScreen.java:1089-1100 negateTime)."""
        for m in self.party.members:
            if getattr(m, "powder", 0) > 0:
                m.powder -= 1
                self.text_log.add_message("Stop time with a powder!")
                self.party.aura.set(AuraType.QUICKNESS, 6)
                self._consume_pass_turn()  # Java keyUp tail: N falls through
                return
        self.text_log.add_message("None!")
        self._consume_pass_turn()  # Java keyUp tail: N falls through

    def _prompt_other(self) -> None:
        """Prompt for custom other command (PRAY, BRIBE, STEAL, DIG, etc.)."""
        def _on_other(cmd: str) -> None:
            c = cmd.strip().upper()
            if not c:
                return
            if c == "PRAY":
                if str(self.map_id) in ("10", "yew") and 44 <= self.party.x <= 52 and 44 <= self.party.y <= 52:
                    self.text_log.add_message("A vision appears: Yell 'EVOCARE'!")
                else:
                    self.text_log.add_message("A calmness and silence of the soul.")
            elif c == "BRIBE":
                self.text_log.add_message("Thou hast no one to bribe here.")
            elif c == "STEAL":
                self.text_log.add_message("Thou art an honest traveler; nothing to steal.")
            elif c == "DIG":
                self.text_log.add_message("Thou diggest into the earth, but findest nothing.")
            elif c == "KISS":
                self.text_log.add_message("Thou kissest the gentle breeze.")
            elif c == "INSERT":
                prompt_insert_card(self, self.party.x, self.party.y)
            else:
                self.text_log.add_message(f"'{c}': Nothing happened.")

        self.text_log.prompt("Other Command? ", callback=_on_other)

    def _prompt_ready_weapon(self) -> None:
        """Equip weapon on selected party member with A-P selection and inventory tracking.

        Java truth: GameScreen.java:608-613 routes R to the shared
        SecondaryInputProcessor / ReadyWearInputAdapter flow; the shared
        implementation now lives in member_prompts.prompt_ready_weapon.
        """
        prompt_ready_weapon(self.text_log, self.party, self.asset_mgr, turn_callback=self._consume_pass_turn)

    def _search(self) -> None:
        """SEARCH: a member 1-4 searches the party's tile (Java SIP:240-250).

        Java truth: ``exodus/BaseMap.searchLocation`` (BaseMap.java:855-937)
        grants the label item once and awards 100 XP; anything else is
        "Nothing here!". The portal and fountain checks below retain this
        port's pre-existing overworld extras.
        """
        def _on_who(who_str: str) -> None:
            pm = self._parse_member(who_str)
            if pm is None:
                self.text_log.add_message("Invalid member #!")
                return

            desc = search_module.search_location(
                self.game_map, self.party, pm, self.party.x, self.party.y
            )
            if desc is not None:
                self.text_log.add_message(f"You found {desc}.")
                return

            # Check portals
            portal = None
            if self.game_map is not None:
                for p in self.game_map.portals:
                    if p.x == self.party.x and p.y == self.party.y:
                        portal = p
                        break

            if portal is not None:
                self.text_log.add_message(f"Search: Thou discoverest an entrance to destination #{portal.dest_map_id}!")
                return

            # Check fountain
            tile = self.game_map.get_tile(self.party.x, self.party.y) if self.game_map else None
            tile_name = getattr(tile, "name", "ground").lower()
            if "fountain" in tile_name:
                self.text_log.add_message("Search: A clear bubbling fountain! Waters refresh the party.")
                for m in self.party.members:
                    if not m.is_dead():
                        m.hp = min(m.max_hp, m.hp + 25)
                return

            self.text_log.add_message("Nothing here!")

        self.text_log.prompt("SEARCH> Which party member? (1-4):", callback=_on_who, single_char=True)

    def _talk(self) -> None:
        """TALK: a member 1-4 speaks at a chosen direction (Java SIP:152-210).

        Java truth: ``SecondaryInputProcessor.java:163-179`` — only a ``signs``
        rule tile steps the gaze one tile further (the vendor sits behind its
        sign); any other blocking tile is just a miss.
        """
        def _on_member(m_str: str) -> None:
            member = self._parse_member(m_str)
            if member is None:
                self.text_log.add_message("Nobody selected!")
                return
            self.text_log.prompt(
                "Direction? (N,S,E,W):",
                callback=lambda d_str: self._talk_direction(d_str, member),
                single_char=True,
            )

        self.text_log.prompt("TALK> Which party member? (1-4):", callback=_on_member, single_char=True)

    def _talk_direction(self, d_str: str, speaker) -> None:
        d = Direction.from_name_or_key(d_str)
        if d is None:
            self.text_log.add_message("Invalid direction!")
            return

        x = self.party.x + d.dx
        y = self.party.y + d.dy

        tile = self.game_map.get_tile(x, y) if self.game_map else None
        if tile is not None and getattr(tile, "rule", "") == "signs":
            # talking to vendor so get the vendor on other side of sign
            x += d.dx
            y += d.dy

        npc = None
        if self.game_map is not None:
            for n in self.game_map.npcs:
                if n.x == x and n.y == y:
                    npc = n
                    break

        if npc is None or getattr(npc, "conversation", None) is None:
            self.text_log.add_message("Funny, no response! ")
            return

        self.text_log.add_message(getattr(npc, "conversation"))

    def _unlock(self) -> None:
        """UNLOCK: a member 1-4 unlocks a chosen direction with one of their
        keys (Java SIP:221-238 — ``member.getPlayer().keys > 0 &&
        bm.unlockDoor(x, y)``, then ``keys--``)."""
        def _on_member(m_str: str) -> None:
            member = self._parse_member(m_str)
            if member is None:
                self.text_log.add_message("Nobody selected!")
                return
            self.text_log.prompt(
                "Direction? (N,S,E,W):",
                callback=lambda d_str: self._unlock_direction(d_str, member),
                single_char=True,
            )

        self.text_log.prompt("UNLOCK> Which party member? (1-4):", callback=_on_member, single_char=True)

    def _unlock_direction(self, d_str: str, member) -> None:
        d = Direction.from_name_or_key(d_str)
        if d is None:
            self.text_log.add_message("Invalid direction!")
            return
        if self.game_map is None:
            self.text_log.add_message("Can't!")
            return
        if getattr(member, "keys", 0) > 0 and door_module.unlock_door(
            self.game_map, self.party.x + d.dx, self.party.y + d.dy
        ):
            self.text_log.add_message("Unlocked!")
            member.keys -= 1
        else:
            self.text_log.add_message("Can't!")

    def _toggle_volume(self) -> None:
        """Toggle game music and sound effects on/off."""
        if self.audio is not None:
            self.audio.enabled = not self.audio.enabled
            if not self.audio.enabled:
                self.audio.stop_music()
                self.text_log.add_message("Volume: Sound and Music MUTED.")
            else:
                self._play_overworld_music()
                self.text_log.add_message("Volume: Sound and Music ENABLED.")
        else:
            self.text_log.add_message("Volume: Audio subsystem unavailable.")
        # Java GameScreen.java:615-622 — V has no early return; consumes a turn.
        self._consume_pass_turn()

    def _prompt_wear_armor(self) -> None:
        """Equip armor on selected party member with A-H selection and inventory tracking.

        Java truth: GameScreen.java:608-613 routes W to the shared member
        flow (member_prompts.prompt_wear_armor).
        """
        prompt_wear_armor(self.text_log, self.party, self.asset_mgr, turn_callback=self._consume_pass_turn)

    def _prompt_yell(self) -> None:
        """YELL: a member 1-4, then a word (Java SIP:252-260 + YellInputAdapter
        522-577 — EVOCARE next to snake tiles, gated on marks[2])."""
        def _on_member(m_str: str) -> None:
            member = self._parse_member(m_str)
            if member is None:
                self.text_log.add_message("Nobody selected!")
                return
            self.text_log.prompt(
                "Yell what? ",
                callback=lambda phrase: self._yell(member, phrase),
            )

        self.text_log.prompt("YELL> Which party member? (1-4):", callback=_on_member, single_char=True)

    def _yell(self, member, phrase: str) -> None:
        word = phrase.strip().upper()
        if not word:
            return
        if word != "EVOCARE":
            self.text_log.add_message("What?")
            return

        gm = self.game_map

        def _is_snake(x: int, y: int) -> bool:
            tile = gm.get_tile(x, y) if gm else None
            return tile is not None and str(getattr(tile, "name", "")).startswith("snake")

        if not (_is_snake(self.party.x, self.party.y - 1) or _is_snake(self.party.x, self.party.y + 1)):
            self.text_log.add_message("No effect.")
            return

        if getattr(member, "marks", [0, 0, 0, 0])[2] > 0:  # Mark of Snake (SIP:546)
            if self.audio is not None:
                self.audio.play_sfx("rocks")
            # Java YellInputAdapter replaces the fixed serpent tiles with
            # water (SIP:548-549).
            self._replace_tile("water", 10, 57)
            self._replace_tile("water", 10, 58)
        else:
            if self.audio is not None:
                self.audio.play_sfx("negative_effect")
            self.text_log.add_message("No effect.")

    def _replace_tile(self, name: str, x: int, y: int) -> None:
        """Java ``GameScreen.replaceTile`` — swap the map tile for `name`."""
        if self.game_map is None:
            return
        tile = None
        if self.asset_mgr is not None:
            tile = self.asset_mgr.get_tile_by_name(name)
        if tile is None:
            from py_exodus.assets import TileDef

            tile = TileDef(index=2, name=name)
        self.game_map.set_tile(x, y, tile)

    def _prompt_attack_overworld(self) -> None:
        """Attack direction in overland map."""
        def _on_dir(d_str: str) -> None:
            d = Direction.from_name_or_key(d_str)
            if d is None:
                self.text_log.add_message("Invalid direction!")
                return
            tx = (self.party.x + d.dx) % (self.game_map.width if self.game_map else 64)
            ty = (self.party.y + d.dy) % (self.game_map.height if self.game_map else 64)

            # Check if wandering creature at target
            found_creature = None
            found_idx = -1
            for idx, c in enumerate(self.creatures):
                if c["x"] == tx and c["y"] == ty:
                    found_creature = c
                    found_idx = idx
                    break

            if found_creature is not None:
                self.creatures.pop(found_idx)
                self._trigger_combat(found_creature.get("tile_name", "orc"))
            else:
                self.text_log.add_message("You attack the empty air!")

        self.text_log.prompt("Attack Direction? (N,S,E,W):", callback=_on_dir, single_char=True)

    def _move_avatar(self, direction: Direction) -> None:
        if self.game_map is None:
            return

        # Ships must first face the direction before moving that way — the
        # turning press consumes the whole turn (finishTurn on the current
        # tile), the second press moves. Java truth:
        # ``exodus/GameScreen.java:461-529`` (``avatarDirection + 1 !=
        # Direction.<D>.getVal()`` branch; horses and foot move at once).
        if self.party.transport == Transport.SHIP and self.heading != direction:
            self.heading = direction
            self._finish_turn(self.game_map.get_tile(self.party.x, self.party.y))
            return

        # Frigate sailing rules
        if self.party.transport == Transport.SHIP:
            # Check headwind
            if direction == self.party.wind_direction.reverse():
                self.text_log.add_message("Sailing against headwinds slows thee!")

        nx = (self.party.x + direction.dx) % self.game_map.width
        ny = (self.party.y + direction.dy) % self.game_map.height

        start_tile = self.game_map.get_tile(self.party.x, self.party.y)

        if can_move_to(self.game_map, nx, ny, transport=self.party.transport, party=self.party):
            # Java exploration movement is never slowed (slowedByTile's only
            # caller is CombatScreen.java:937, combat creatures only) — no
            # speed roll on the 2D move paths.
            # Java updates the avatar's facing after a successful move only
            # (GameScreen.java:478, 495, 512, 529); a blocked turn leaves it.
            self.heading = direction
            self.party.x = nx
            self.party.y = ny
            if self.audio is not None:
                self.audio.play_sfx("walk_normal")

            self._finish_turn(start_tile)

            # Java preMove intercepts the step onto Ambrosia's WHIRLPOOL
            # portal and ferries the party to a random Sosaria coast tile
            # (GameScreen.java:661-670).
            if portal_entry.step_in_whirlpool_portal(self, nx, ny):
                return

            # Check moongate teleports
            self._check_moongates()

            # Check random encounters
            if self.random_encounters_enabled:
                self._check_random_encounter()
        else:
            if self.audio is not None:
                self.audio.play_sfx("blocked")

    def _check_hull_integrity(self) -> None:
        """Sink a ship whose hull has reached 0, killing the whole party.

        Java truth: ``exodus/GameScreen.java:1181-1197`` ``checkHullIntegrity``
        — while on a ship with ``shiphull <= 0``: "Thy ship sinks!", then
        ``killAll()`` and ``partyDeath()``. The screen's post-check
        (``check_party_death``) routes the game-over flow (Task 2).
        """
        if self.party.transport == Transport.SHIP and self.party.ship_hull <= 0:
            self.text_log.add_message("Thy ship sinks!")
            self.party.kill_all()

    def _finish_turn(self, effect_tile=None) -> None:
        """End the movement turn: sink check, aura tick, submorsel tick, tile
        effect, then the whirlpool engulf scan.

        Java truth: ``exodus/GameScreen.java:706-754`` ``finishTurn`` —
        ``checkHullIntegrity`` runs first, then turn end runs ``endTurn``,
        ``aura.passTurn`` and applies the tile-rule effect of the tile the
        party occupies at the start of the turn (``getCurrentMapCoords`` is
        captured pre-move, so the effect lands on the tile being left, not
        the one entered); moves and the pass key route through it. The
        whirlpool engulf sits inside ``moveObjects`` (``BaseMap.java:540-553``
        at Chebyshev distance ≤ 1), which runs last. A wipe raises
        ``PartyDeathException``; the post-check routes the game-over flow
        (Task 2). The 1-in-4 hull repair sits in ``endTurn``'s Sosaria branch
        (``Party.java:633-638``), so ``sosaria`` tracks the current map id.
        """
        sosaria = str(getattr(self.game_map, "id", self.map_id)) == "0"
        try:
            self._check_hull_integrity()
            # Java order (GameScreen.java:710-714): endTurn, then aura.passTurn.
            self.party.end_turn(surface=True, sosaria=sosaria)
            self.party.aura.pass_turn()
            tile_effects.apply_rule_effect(self.party, effect_tile)
        except PartyDeathException:
            pass
        if self.check_party_death():
            return
        self._check_whirlpool_engulf()

    ENGULF_LINES = (
        "A huge swirling Whirlpool engulfs you and your ship dragging both to a watery grave!",
        "As the water enters your lungs you pass into Darkness!",
        "You awaken on the shores of a forgotten Land.",
        "Your ship and crew lost to the sea!",
    )

    def _check_whirlpool_engulf(self) -> None:
        """Sailing within one tile of a whirlpool engulfs the party's ship.

        Java truth: the whirlpool creature branch of ``moveObjects`` at
        ``dist <= 1`` (``objects/BaseMap.java:540-553``) — four log lines,
        transport set to FOOT (ship and crew lost), and the party ferried to
        Ambrosia (32, 54). The two Sosaria whirlpools live at (50, 13) and
        (17, 48) (``GameScreen.java:111-121``). Under a QUICKNESS aura
        ``moveObjects`` is skipped entirely (``GameScreen.java:728-731``), so
        no engulf happens while time is quick.
        """
        if self.game_map is None:
            return
        if self.party.aura.get_type() == AuraType.QUICKNESS:
            return

        for c in self.creatures:
            if c.get("tile_name") != "whirlpool":
                continue
            wx, wy = c.get("x", -99), c.get("y", -99)
            if not (0 <= wx < self.game_map.width and 0 <= wy < self.game_map.height):
                # Whirlpools only exist where they were placed on Sosaria
                # (GameScreen.java:111-121); never engulf from an off-map
                # fixture position.
                continue
            dx = abs(wx - self.party.x)
            dy = abs(wy - self.party.y)
            dx = min(dx, self.game_map.width - dx)
            dy = min(dy, self.game_map.height - dy)
            if max(dx, dy) <= 1:
                if self.audio is not None:
                    self.audio.play_sfx("wave")
                for line in self.ENGULF_LINES:
                    self.text_log.add_message(line)
                self.party.transport = Transport.FOOT
                self.party.x, self.party.y = 32, 54
                self.map_id = 13
                self._load_world_map()
                self._play_overworld_music()
                return

    def _prompt_fire_cannons(self) -> None:
        """Fire frigate broadside cannons in a given direction."""
        def _on_dir(d_str: str) -> None:
            d = Direction.from_name_or_key(d_str)
            if d is None:
                self.text_log.add_message("Invalid firing direction!")
                return
            self._fire_cannons(d)

        self.text_log.prompt("Fire cannon direction? (N,S,E,W):", callback=_on_dir, single_char=True)

    def _fire_cannons(self, direction: Direction) -> None:
        if self.party.transport == Transport.SHIP:
            if self.heading in (Direction.NORTH, Direction.SOUTH):
                valid_dirs = (Direction.WEST, Direction.EAST)
            else:
                valid_dirs = (Direction.NORTH, Direction.SOUTH)
            if direction not in valid_dirs:
                self.text_log.add_message("Broadsides only!")
                return

        if self.audio is not None:
            self.audio.play_sfx("cannon") or self.audio.play_sfx("enemy_magic_proj")

        self.text_log.add_message(f"BOOM! Broadside fired {direction.name}!")

        # Trace cannonball up to 4 tiles (Java Utils.java:539-546, 403-421 —
        # getDirectionalActionPath(min 1, max 4))
        if self.game_map is None:
            return
        cx, cy = self.party.x, self.party.y
        for step in range(1, 5):
            tx = (cx + direction.dx * step) % self.game_map.width
            ty = (cy + direction.dy * step) % self.game_map.height

            # Empty frigate in the path: hit, 10 hull damage, trace stops.
            # Java truth: ``util/Utils.java:539-546`` ``fireAt`` — either
            # broadside striking an unmanned frigate damages it (10) and
            # ends the volley before any creature check.
            for obj in self.party.dynamic_objects:
                if (
                    str(obj.get("tile", "")).lower() in ("frigate", "ship")
                    and obj.get("x") == tx
                    and obj.get("y") == ty
                ):
                    obj["hull"] = obj.get("hull", 50) - 10
                    self.text_log.add_message("Direct hit on an unmanned frigate!")
                    return

            # Check creature hit
            hit_creature = None
            for c in list(self.creatures):
                if c.get("x") == tx and c.get("y") == ty:
                    hit_creature = c
                    break

            if hit_creature is not None:
                c_name = hit_creature.get("tile_name", "creature").capitalize()
                hp = hit_creature.get("hp", 50)
                damage = random.randint(30, 60)
                hp -= damage
                hit_creature["hp"] = hp
                if hp <= 0:
                    self.creatures.remove(hit_creature)
                    self.text_log.add_message(f"Direct hit! The {c_name} sinks into the sea!")
                else:
                    self.text_log.add_message(f"Direct hit on {c_name}!")
                break

            tile = self.game_map.get_tile(tx, ty)
            if tile is not None and not tile.walkable and not tile.sailable:
                self.text_log.add_message("Cannonball crashed into the shoreline!")
                break

    def _enter_portal(self) -> None:
        """Enter the portal at the party's tile (Java GameScreen.java:538-556).

        E is available on every map. The Ambrosia→Sosaria WHIRLPOOL portal
        goes to the portal's fixed startx/starty (maps.xml ``startx="1"``
        starty="1"``); stepping onto it instead uses Java ``preMove``'s
        random coast (``GameScreen.java:661-670``) — see
        ``world.portal_entry.step_in_whirlpool_portal``.
        """
        if self.game_map is None:
            return
        if not portal_entry.enter_portal(self, self.party.x, self.party.y):
            # Java GameScreen.java:538-556 — no portal on the tile: E falls
            # through SILENTLY to the keyUp tail, which consumes the turn.
            self._consume_pass_turn()

    _toggle_board_transport = _board_transport

    def _check_moongates(self) -> None:
        """Check if party stepped onto an active moongate."""
        if self.game_map is None:
            return

        active_gate = None
        for gate in self.game_map.moongates:
            if gate.phase == self.trammel_phase:
                active_gate = gate
                break

        if active_gate is None:
            return

        if active_gate.x == self.party.x and active_gate.y == self.party.y:
            if self.felucca_phase == active_gate.phase:
                return

            dest_gate_phase = -1
            if self.felucca_phase == active_gate.d1:
                dest_gate_phase = active_gate.d1
            elif self.felucca_phase == active_gate.d2:
                dest_gate_phase = active_gate.d2
            elif self.felucca_phase == active_gate.d3:
                dest_gate_phase = active_gate.d3

            if dest_gate_phase >= 0:
                dest_gate = None
                for g in self.game_map.moongates:
                    if g.phase == dest_gate_phase:
                        dest_gate = g
                        break
                if dest_gate is not None:
                    self.party.x = dest_gate.x
                    self.party.y = dest_gate.y
                    self.text_log.add_message("Stepped through mystical moongate!")
                    if self.audio is not None:
                        self.audio.play_sfx("moongate_flash")

    def _spawn_wandering_creature(self) -> None:
        """Spawn a wandering creature near the edge of the viewport."""
        if self.game_map is None or len(self.creatures) >= 8:
            return

        import random
        dist_x = random.randint(8, 12) * random.choice([-1, 1])
        dist_y = random.randint(8, 12) * random.choice([-1, 1])
        sx = (self.party.x + dist_x) % self.game_map.width
        sy = (self.party.y + dist_y) % self.game_map.height

        tile = self.game_map.get_tile(sx, sy)
        if tile is None:
            return

        t_name = getattr(tile, "name", "grass").lower()
        if "water" in t_name or "sea" in t_name:
            c_name = random.choice(["pirate", "serpent", "squid"])
        elif "forest" in t_name or "brush" in t_name:
            c_name = random.choice(["giant", "thief", "skeleton"])
        else:
            c_name = random.choice(["orc", "skeleton", "giant", "thief"])

        self.creatures.append({
            "name": c_name.capitalize(),
            "tile_name": c_name,
            "tile": c_name,
            "x": sx,
            "y": sy,
        })

    def _update_creatures(self) -> None:
        """Move wandering creatures towards the party or wander.

        Java truth: the QUICKNESS aura skips ``moveObjects`` for the turn
        (``GameScreen.java:728-731``) — no creature advance while time is
        quick. Whirlpool creatures never move and never engage.
        """
        if not self.creatures and self.random_encounters_enabled:
            self._spawn_wandering_creature()

        import random
        if self.random_encounters_enabled and random.random() < 0.25 and len(self.creatures) < 6:
            self._spawn_wandering_creature()

        # Java GameScreen.java:728-731 — moveObjects is skipped entirely
        # while a QUICKNESS aura is active.
        if self.party.aura.get_type() == AuraType.QUICKNESS:
            return

        width = self.game_map.width if self.game_map else 64
        height = self.game_map.height if self.game_map else 64

        survivors: list[dict[str, Any]] = []
        encounter_creature = None

        for c in self.creatures:
            cx, cy = c["x"], c["y"]

            if c.get("tile_name") == "whirlpool":
                # Java moveObjects still walks whirlpools a random direction
                # on open water (wontattack), but they never travel to the
                # party: keep them parked where they were placed.
                survivors.append(c)
                continue

            # If already on the party, engage and remove
            if cx == self.party.x and cy == self.party.y:
                if encounter_creature is None:
                    encounter_creature = c
                continue

            dx = self.party.x - cx
            dy = self.party.y - cy

            if dx > width // 2:
                dx -= width
            elif dx < -width // 2:
                dx += width
            if dy > height // 2:
                dy -= height
            elif dy < -height // 2:
                dy += height

            step_x = 1 if dx > 0 else (-1 if dx < 0 else 0)
            step_y = 1 if dy > 0 else (-1 if dy < 0 else 0)

            if abs(dx) > abs(dy) or (abs(dx) == abs(dy) and random.random() < 0.5):
                nx = (cx + step_x) % width
                ny = cy
            else:
                nx = cx
                ny = (cy + step_y) % height

            tile = self.game_map.get_tile(nx, ny) if self.game_map else None
            is_sea = c.get("tile_name") in ("pirate", "serpent", "squid")
            if tile is not None:
                is_water = "water" in tile.name.lower() or "sea" in tile.name.lower()
                if (is_sea and is_water) or (not is_sea and not is_water and tile.walkable):
                    cx, cy = nx, ny

            c["x"] = cx
            c["y"] = cy

            # Check collision with party
            if cx == self.party.x and cy == self.party.y:
                if encounter_creature is None:
                    encounter_creature = c
                continue

            survivors.append(c)

        self.creatures = survivors

        if encounter_creature is not None:
            self._trigger_combat(encounter_creature.get("tile_name", "orc"))

    def _trigger_combat(self, creature_name: str) -> None:
        """Initiate tactical combat screen with creature."""
        if self.asset_mgr is None:
            return

        c_tile = creature_name.lower()
        if c_tile not in ("orc", "skeleton", "giant", "thief", "daemon", "dragon", "balron", "pirate", "serpent", "squid"):
            c_tile = "orc"

        tile = self.game_map.get_tile(self.party.x, self.party.y) if self.game_map else None
        tile_name = getattr(tile, "name", "grass").lower()

        if c_tile in ("pirate", "serpent", "squid") or "water" in tile_name:
            conflict_map_id = 41
        elif "brush" in tile_name or "forest" in tile_name:
            conflict_map_id = 34
        else:
            conflict_map_id = 37

        try:
            from py_exodus.screens.combat_screen import CombatScreen
            from py_exodus.world.loader import MapLoader

            loader = MapLoader(self.asset_mgr)
            c_map = loader.load_conflict_map(conflict_map_id)
            combat_scr = CombatScreen(
                party=self.party,
                combat_map=c_map,
                creature_tile=c_tile,
                asset_mgr=self.asset_mgr,
                audio=self.audio,
                return_screen=self,
                manager=self.manager,
            )
            if self.manager is not None:
                self.manager.push_screen(combat_scr)
            else:
                self.next_screen = combat_scr
                self.is_finished = True
        except Exception:
            pass

    def _check_random_encounter(self) -> None:
        """Advance wandering creatures and check proximity encounters."""
        self._update_creatures()

    def _save_game(self) -> None:
        """Save party progress to JSON file.

        Java truth: GameScreen.java:557-563 — Q is the save command on every
        GameScreen map, but only SOSARIA (map id 0) accepts it: "Saved Game."
        there, "Cannot save here!" anywhere else. Both paths fall through the
        keyUp tail and consume a turn.
        """
        if getattr(self.game_map, "id", None) == 0:
            try:
                from py_exodus.save_system import SaveSystem

                SaveSystem.save_game(self.party, "saves/party.json")
                self.text_log.add_message("Saved Game.")
            except Exception:
                self.text_log.add_message("Save failed!")
        else:
            self.text_log.add_message("Cannot save here!")
        self._consume_pass_turn()

    def update(self, dt: float) -> None:
        self.anim_timer += dt
        if self.anim_timer >= 0.2:
            self.anim_timer = 0.0
            self.anim_frame = (self.anim_frame + 1) % 4

        self.moon_timer += dt
        if self.moon_timer >= 4.0:
            self.moon_timer = 0.0
            self.moon_phase = (self.moon_phase + 1) % 24
            # Random wind shift
            if random.random() < 0.15:
                dirs = list(Direction)
                self.party.wind_direction = random.choice(dirs)

        self.party.moons = self.moons

    def render(self, surface: pygame.Surface) -> None:
        surface.fill(EGA_BLACK)
        w, h = surface.get_width(), surface.get_height()
        scale = 3 if w >= 640 else 1
        v_size = 176 * scale

        if scale > 1:
            temp_v = pygame.Surface((176, 176))
            if self.world_renderer is not None and self.game_map is not None:
                self.world_renderer.render_viewport(
                    temp_v,
                    self.game_map,
                    center_x=self.party.x,
                    center_y=self.party.y,
                    anim_frame=self.anim_frame,
                    party=self.party,
                    dest_pos=(0, 0),
                    monsters=self.creatures,
                )
            scaled_v = pygame.transform.scale(temp_v, (v_size, v_size))
            surface.blit(scaled_v, (0, 0))

            # Right Sidebar (Party Stats) at native high resolution
            self.stats_panel.render(
                surface,
                self.party,
                rect=pygame.Rect(v_size, 0, w - v_size, h),
            )

            # Bottom HUD Text Log at native resolution
            self.text_log.render(
                surface,
                rect=pygame.Rect(0, v_size, v_size, h - v_size),
                draw_border=True,
            )
        else:
            if self.world_renderer is not None and self.game_map is not None:
                self.world_renderer.render_viewport(
                    surface,
                    self.game_map,
                    center_x=self.party.x,
                    center_y=self.party.y,
                    anim_frame=self.anim_frame,
                    party=self.party,
                    dest_pos=(0, 0),
                    monsters=self.creatures,
                )
            self.stats_panel.render(
                surface,
                self.party,
                rect=pygame.Rect(176, 0, w - 176, h),
            )
            log_h = max(24, h - 176)
            self.text_log.render(
                surface,
                rect=pygame.Rect(0, 176, 176, log_h),
                draw_border=True,
            )
