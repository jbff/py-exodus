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
    TileAttrib,
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
    from py_exodus.entities.defs import CreatureDef
    from py_exodus.entities.party import Party
    from py_exodus.world.map import GameMap


def get_combat_map_id(
    creature: CreatureDef | str,
    creature_x: int,
    creature_y: int,
    party_x: int,
    party_y: int,
    transport: Transport,
    game_map: GameMap | None,
) -> int:
    """Java ``Context.getCombatMap`` (Context.java:303-326) port.

    The base arena is the COMBAT-MAP RULE of the tile the creature stands on
    (``bm.getTile(creatureX, creatureY).getCombatMap()``). A swimming creature
    lands on CONFLICT_SHORE and a sailing one on CONFLICT_SHIP_TOP when the
    party's tile is walkable — so a sea creature met on land never forces
    BOTH_SHIPS. Sailing overrides everything for the whole encounter."""

    def _tile(x: int, y: int) -> Any:
        return game_map.get_tile(x, y) if game_map is not None else None

    c_tile = _tile(creature_x, creature_y)
    combat_map_id = getattr(c_tile, "combat_map_id", None)
    if combat_map_id is None:
        combat_map_id = getattr(c_tile, "combat_map", 37)
    party_tile = _tile(party_x, party_y)
    party_unwalkable = bool(
        getattr(party_tile, "attribs", 0) & TileAttrib.UNWALKABLE
    ) if party_tile is not None else False

    swims = getattr(creature, "swims", False) if not isinstance(creature, str) else False
    sails = getattr(creature, "sails", False) if not isinstance(creature, str) else False
    tile_name = getattr(
        creature, "tile", creature if isinstance(creature, str) else ""
    ).lower()

    if swims and not party_unwalkable:
        combat_map_id = 38  # CONFLICT_SHORE
    elif sails and not party_unwalkable:
        combat_map_id = 33  # CONFLICT_SHIP_TOP (CONFLICT_SHORE's sail variant)

    if transport == Transport.SHIP:
        if sails or tile_name == "pirate":
            combat_map_id = 41  # CONFLICT_BOTH_SHIPS
        elif swims:
            combat_map_id = 39  # CONFLICT_SHIP
        else:
            combat_map_id = 40  # CONFLICT_SHIP_BOTTOM

    return combat_map_id


# --- Overworld HUD sky strip (Java GameScreen.java:180-196) ------------------ #
# On Sosaria (map id 0) Java draws two moon-phase icons (Trammel and Felucca),
# the "Wind <direction>" text, the aura label while active, and "Hull: N" when
# on a ship. Port adaptation (documented per the strip ruling): the phase atlas
# icons become clipped circle-with-shadow EGA glyphs and the wind/aura text
# keeps the port's font-drawn text style. Hull is NOT duplicated here — the
# stats panel transport row already carries "SHIP (HULL:n)".
WIND_ARROWS: dict[Direction, str] = {
    Direction.NORTH: "^",
    Direction.SOUTH: "v",
    Direction.EAST: ">",
    Direction.WEST: "<",
}


def sky_strip_texts(
    wind_direction: Direction,
    trammel_phase: int,
    felucca_phase: int,
    aura: "AuraType | None" = None,
) -> list[str]:
    """Text lines of the sky strip (wind + moons, plus the aura label first
    when active — Java GameScreen.java:184,188-189)."""
    texts: list[str] = []
    if aura is not None and aura != AuraType.NONE:
        texts.append(aura.name)
    texts.append(f"Wind {wind_direction.name} {WIND_ARROWS[wind_direction]}")
    texts.append(f"T:{trammel_phase} F:{felucca_phase}")
    return texts


def draw_moon_glyph(
    surface: pygame.Surface,
    cx: int,
    cy: int,
    radius: int,
    phase: int,
    lit_color: tuple[int, int, int] = EGA_WHITE,
    dark_color: tuple[int, int, int] = EGA_DARK_GRAY,
) -> None:
    """One 8-phase moon glyph clipped to its disc (Java draws the phase_0..7
    atlas icons; the port renders a circle-with-shadow glyph from EGA colors).
    Phase 0 is new moon (fully dark disc), 4 is full — the same counting the
    Dawn double-new-moon gate restriction uses."""

    def _rgba(c: tuple[int, int, int]) -> tuple[int, int, int, int]:
        return (c[0], c[1], c[2], 255)

    size = 2 * radius + 3
    glyph = pygame.Surface((size, size), pygame.SRCALPHA)
    center = (size // 2, size // 2)
    pygame.draw.circle(glyph, _rgba(lit_color), center, radius)
    # Dark shadow disc slides across: offset 0 = eclipsed (new moon), 2r =
    # fully clear (full moon); waxing phases shadow from the left, waning
    # from the right.
    mag = (0, radius // 2, radius, 2 * radius - 1, 0, 2 * radius - 1, radius, radius // 2)[
        phase % 8
    ]
    if phase % 8 != 4:
        # Phase 4 (full) skips the shadow entirely; phase 0 keeps its
        # centered shadow (mag 0) so the new moon is an eclipsed dark disc,
        # visually distinct from the fully lit full moon.
        from_left = phase % 8 < 4
        sx = center[0] - mag if from_left else center[0] + mag
        pygame.draw.circle(glyph, _rgba(dark_color), (sx, center[1]), radius)
    # Circular clip: everything outside the moon disc is removed.
    mask = pygame.Surface((size, size), pygame.SRCALPHA)
    pygame.draw.circle(mask, (255, 255, 255, 255), center, radius)
    glyph.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    surface.blit(glyph, (cx - size // 2, cy - size // 2))


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
        world_state: dict[str, Any] | None = None,
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
        # Java GameScreen.java:280-330 restore-on-load: the Journey Onward
        # starter rebuilds the saved SOSARIA monsters onto the map before any
        # new wandering spawn. The map's own objects come back through
        # party.dynamic_objects (serialized with the party record).
        self._restore_world_state(world_state)

        self.anim_frame = 0
        # Peer Gem (P) view state (Java PeerGemInputAdapter, see gem_view).
        self.gem_view_active = False
        self.anim_timer = 0.0
        self.moon_timer = 0.0
        self.moon_phase = 0

        self.world_renderer = (
            WorldRenderer(asset_mgr) if asset_mgr is not None else None
        )
        self.stats_panel = StatsPanel(asset_mgr=self.asset_mgr)
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

    @property
    def sky_strip_active(self) -> bool:
        """Sosaria only (Java GameScreen.java:186 gates the moon/wind HUD on
        Maps.SOSARIA.getId()); Ambrosia and other overworld maps get nothing."""
        return str(self.map_id) == "0"

    def sky_strip_texts(self) -> list[str]:
        """The strip's text lines from the LIVE state: the phases come from
        self.trammel_phase / self.felucca_phase (the same properties the
        moongate routing reads) and the wind from party.wind_direction —
        never copies. Empty when the strip is not active."""
        if not self.sky_strip_active:
            return []
        return sky_strip_texts(
            self.party.wind_direction,
            self.trammel_phase,
            self.felucca_phase,
            aura=self.party.aura.get_type(),
        )

    def _render_sky_strip(self, surface: pygame.Surface, pane_right: int, pane_top: int) -> None:
        """Draw the top strip of the main pane: the aura label while active,
        the wind text with its direction arrow, and the two moon-phase glyphs
        (Trammel and Felucca) right-aligned (Java GameScreen.java:180-196).
        Hull is not duplicated here — the stats panel transport row already
        shows "SHIP (HULL:n)" while sailing."""
        if not self.sky_strip_active:
            return

        scale = 3 if surface.get_width() >= 640 else 1
        margin = 2 * scale
        radius = max(2, 4 * scale)
        f = get_hud_font(size=8 * scale if scale > 1 else 8)

        y = pane_top + margin
        aura = self.party.aura.get_type()
        if aura != AuraType.NONE:
            surface.blit(f.render(aura.name, False, EGA_YELLOW), (margin, y))
            y += f.get_linesize()

        wind = self.party.wind_direction
        wind_txt = f"Wind {wind.name} {WIND_ARROWS[wind]}"
        surface.blit(f.render(wind_txt, False, EGA_LIGHT_GRAY), (margin, y))
        moon_txt = f"T:{self.trammel_phase} F:{self.felucca_phase}"
        surface.blit(
            f.render(moon_txt, False, EGA_WHITE),
            (margin + f.size(wind_txt)[0] + 3 * scale, y),
        )

        size = 2 * radius + 3
        gx2 = pane_right - margin - radius - 2
        gx1 = gx2 - radius - 1 - size
        cy = y + f.get_linesize() // 2
        draw_moon_glyph(surface, gx1, cy, radius, self.trammel_phase)
        draw_moon_glyph(surface, gx2, cy, radius, self.felucca_phase)

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
        # Mouse wheel scrolls the shared text log back through history
        # (Java LogScrollPane affordance). The peer-gem view owns all input,
        # so the wheel neither scrolls nor closes it (GameScreen.java:1146-1152).
        if event.type == pygame.MOUSEWHEEL:
            if not self.gem_view_active:
                self.text_log.handle_wheel(event)
            return

        if event.type != pygame.KEYDOWN:
            return

        # Java PeerGemInputAdapter.keyUp (GameScreen.java:1146-1152): while
        # the gem view is up it owns ALL input; any key closes it and
        # restores the timer, with no turn passing.
        if self.gem_view_active:
            self.gem_view_active = False
            return

        if self.text_log.is_waiting_for_input:
            self.text_log.handle_event(event)
            return

        # PageUp/PageDown always scroll the text log back (arrow keys scroll
        # only inside the log's own prompt handling, when they cannot act as
        # direction/command answers).
        if self.text_log.handle_scroll_key(event.key):
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
        prompt_cast_party(
            self.text_log,
            self.party,
            world_map=self.game_map,
            audio=self.audio,
            view_callback=self._show_vieda_view,
        )

    def _show_vieda_view(self) -> None:
        """Java SpellUtil.spellView (SpellUtil.java:494-499) hands input to the
        peer-gem adapter — the surrounding-area survey, without consuming a
        gem (unlike the P command)."""
        m_name = getattr(self.game_map, "name", "Sosaria")
        self.text_log.add_message(f"Gem vision: {m_name} at X={self.party.x}, Y={self.party.y}.")

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
        through the keyUp tail (GameScreen.java:628), so the press consumes
        a turn either way, before the view opens. peerGem itself
        (GameScreen.java:1076-1087) uses the FIRST member holding gems with
        no member prompt, logs "Peer at a Gem!" and swaps input to
        PeerGemInputAdapter (map view, timer paused); with none it logs
        "Thou dost have no gems!".
        """
        from py_exodus.ui.gem_view import (
            NO_GEMS_MESSAGE,
            PEER_MESSAGE,
            consume_peer_gem,
        )

        if consume_peer_gem(self.party) is not None:
            self.text_log.add_message(PEER_MESSAGE)
            # Java: gameTimer.active = False while viewing; the exit key
            # costs no turn (test_gem_view_exit_consumes_no_turn).
            self.gem_view_active = True
        else:
            self.text_log.add_message(NO_GEMS_MESSAGE)
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
                self._trigger_combat(
                    found_creature.get("tile_name", "orc"), found_creature
                )
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
        (``Party.java:633-638``), so ``sosaria`` tracks the current map id;
        the 40-submorsel interval is surface maps SOSARIA (0) and EXODUS (2)
        only — Ambrosia (13) drains at 10 (``Party.java:598-600``).
        """
        map_id = str(getattr(self.game_map, "id", self.map_id))
        sosaria = map_id == "0"
        try:
            self._check_hull_integrity()
            # Java order (GameScreen.java:710-714): endTurn, then aura.passTurn.
            self.party.end_turn(surface=map_id in ("0", "2"), sosaria=sosaria)
            # USER-DIRECTED ORIGINAL-RULES DEVIATION (2026-11-10): Java's
            # Party.endTurn regenerated mana/HP/poison only at the meal
            # crossing (Party.java:612-617). The U3 Book of Play ties those
            # to the TURN ("A character replenishes that energy at a rate of
            # one point per turn on the surface, and one point every four
            # turns in a town or dungeon"; "Every step the character takes,
            # lowers the character's hit level by one" for poison), so the
            # regen tick runs every consumed turn here. Surface means the
            # overworld screen — Sosaria AND Ambrosia; the map_id in
            # ("0","2") decision above is the food interval only.
            self.party.tick_regen(surface=True)
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
            self._trigger_combat(
                encounter_creature.get("tile_name", "orc"), encounter_creature
            )

    def _trigger_combat(self, creature_name: str, creature: dict[str, Any] | None = None) -> None:
        """Initiate tactical combat screen with creature.

        Java truth: the arena map comes from ``Context.getCombatMap``
        (Context.java:303-326) — the tile-rule combat map of the tile the
        CREATURE stands on, overridden by the swim/sail variants and the
        party's transport.
        """
        if self.asset_mgr is None:
            return

        c_tile = creature_name.lower()
        if c_tile not in ("orc", "skeleton", "giant", "thief", "daemon", "dragon", "balron", "pirate", "serpent", "squid"):
            c_tile = "orc"

        creature_x = int(creature.get("x", self.party.x)) if creature else self.party.x
        creature_y = int(creature.get("y", self.party.y)) if creature else self.party.y
        c_def = self.asset_mgr.get_creature(c_tile)
        if c_def is None:
            c_def = self.asset_mgr.get_creature("thief" if c_tile == "pirate" else c_tile)

        conflict_map_id = get_combat_map_id(
            c_def if c_def is not None else creature_name,
            creature_x,
            creature_y,
            self.party.x,
            self.party.y,
            self.party.transport,
            self.game_map,
        )

        # Java GameScreen.endCombat (GameScreen.java:416-431) re-reads the
        # encounter CREATURE's overworld tile at combat end: the chest lands
        # there when the tile is walkable, a pirate otherwise leaves a frigate.
        encounter_tile = self.game_map.get_tile(creature_x, creature_y) if self.game_map else None
        encounter_unwalkable = bool(
            getattr(encounter_tile, "attribs", 0) & TileAttrib.UNWALKABLE
        ) if encounter_tile is not None else False

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
                context_map_id=self.game_map.id if self.game_map else None,
                encounter_x=creature_x,
                encounter_y=creature_y,
                encounter_tile_walkable=not encounter_unwalkable,
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

    def _restore_world_state(self, world_state: dict[str, Any] | None) -> None:
        """Rebuild the saved wandering/sea creatures onto the Sosaria map.

        Java truth: ``GameScreen.java:300-312`` — after loading the save game,
        up to 8 monsters are re-created on the SOSARIA map from the saved
        tile ids/positions. User ruling (2026-11-10 amendment): whirlpools
        are NOT excluded, so a saved block owns the fixtures too — the free
        re-seed from ``_load_world_map`` is dropped here (exactly those
        entries are replaced by the saved ones, so there can never be
        duplicates); without a block (legacy saves) the Task 9 re-seed
        fallback stays untouched. Mid-session map prepares (Ambrosia
        round trips) keep re-seeding via ``_load_world_map`` per Java
        GameScreen.java:111-121. ``on_enter`` then purges any creature
        standing on the party's tile (combat re-trigger guard). Saved world
        state only ever originates from a Sosaria Q-save, so non-Sosaria
        loads ignore it. Documented deviation (user ruling 2026-11-10,
        R2 rider): a saved creature's ``hp`` is restored too — Java's
        GameScreen.java:300-312 rebuilds monsters at full health and
        discards the saved hp.
        """
        if not world_state or str(self.map_id) != "0":
            return
        # Guard a malformed block (R1): a hand-edited save can carry a
        # non-dict "overworld" value (e.g. a bare list). Treat it as absent
        # — the free re-seed fallback stays (Java degrades to the roster
        # screen on an unreadable record rather than crashing).
        if not isinstance(world_state, dict):
            return
        # The block owns the whirlpool fixtures at load: drop the free
        # re-seed before restoring, so the saved fixtures replace them
        # (no duplicates).
        self.creatures = [
            c for c in self.creatures if c.get("tile_name") != "whirlpool"
        ]
        for m in world_state.get("monsters", [])[:8]:
            tile_name = str(m.get("tile_name", "")).lower()
            if not tile_name:
                continue
            creature = {
                "name": str(m.get("name", "")),
                "tile_name": tile_name,
                "tile": str(m.get("tile", m.get("tile_name", ""))),
                "x": int(m.get("x", 0)),
                "y": int(m.get("y", 0)),
            }
            if tile_name == "whirlpool":
                # Fixtures are restored with the non-engaging fixture
                # behavior (never move, never attack) that free-seeded
                # whirlpools carry.
                creature["wontattack"] = True
            if m.get("hp") is not None:
                creature["hp"] = int(m["hp"])
            self.creatures.append(creature)

    def _save_game(self) -> None:
        """Save party progress to JSON file.

        Java truth: GameScreen.java:557-563 — Q is the save command on every
        GameScreen map, but only SOSARIA (map id 0) accepts it: "Saved Game."
        there, "Cannot save here!" anywhere else. Both paths fall through the
        keyUp tail and consume a turn.

        Java Context.saveGame (Context.java:138-193) additionally serializes
        the SOSARIA map's dynamic state into the party record: the first 8
        map creatures in list order with positions and tile ids, and the map
        objects (embarked frigates/chests) — the objects already live in
        ``party.dynamic_objects`` here and ride along in the party dict.
        GameScreen.java:280-330 restores both on the next load.
        Documented deviation (user ruling 2026-11-10): whirlpool entries are
        NOT skipped the way Java's Context.saveGame does (Java `continue`s
        whirlpools without freeing the slot); the first 8 creatures save
        regardless of kind, so the fixtures ride in the block.
        Documented deviation (user ruling 2026-11-10, R2 rider): a
        creature's current ``hp`` persists in the block — Java's
        Context.saveGame records tile ids/positions only and discards hp,
        so a restored monster here resumes at the health it had.
        """
        if getattr(self.game_map, "id", None) == 0:
            try:
                from py_exodus.save_system import SaveSystem

                saved_monsters = []
                # First 8 creatures in list order regardless of kind
                # (user ruling 2026-11-10: whirlpools save like any other
                # creature — Java's skip-without-freeing-slot quirk is
                # deliberately NOT reproduced).
                for c in self.creatures[:8]:
                    entry = {
                        "name": c.get("name", ""),
                        "tile_name": c.get("tile_name", ""),
                        "tile": c.get("tile", ""),
                        "x": int(c.get("x", 0)),
                        "y": int(c.get("y", 0)),
                    }
                    if c.get("hp") is not None:
                        entry["hp"] = int(c["hp"])
                    saved_monsters.append(entry)

                SaveSystem.save_game(
                    self.party,
                    "saves/party.json",
                    extra={"overworld": {"monsters": saved_monsters}},
                )
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

        # Peer Gem view (Java PeerGemInputAdapter): the gem picture replaces
        # the whole screen (GameScreen.java:1119-1129 — the image is added
        # over the stage and the HUD is not shown; the port drops to a plain
        # colored-cell map, see py_exodus/ui/gem_view.py).
        if self.gem_view_active and self.game_map is not None:
            from py_exodus.ui.gem_view import render_gem_view

            marks = [
                (npc.x, npc.y)
                for npc in self.game_map.npcs
            ]
            marks.extend(
                (c["x"], c["y"]) for c in self.creatures
            )
            render_gem_view(surface, self.game_map, self.party.x, self.party.y, marks=marks)
            return

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
            self._render_sky_strip(surface, pane_right=v_size, pane_top=0)

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
            self._render_sky_strip(surface, pane_right=176, pane_top=0)
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
