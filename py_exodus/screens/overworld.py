"""Overworld exploration screen for Sosaria and Ambrosia."""
from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

import pygame

from py_exodus import debug
from py_exodus.assets import MAP_ID_TO_LABEL, MAP_NAME_TO_ID
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
from py_exodus import special_commands
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
from py_exodus.world.monster_variants import roll_variant, variant_name
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
    elif swims and combat_map_id == 41:
        # Sea swimmers (serpent/squid) never fight ship-to-ship.
        combat_map_id = 38  # CONFLICT_SHORE

    return combat_map_id


# --- moveObjects creature-half helpers (Java objects/BaseMap.java:421-610) --- #

# Original U3 monster table size (LairWare UltimaMisc.c:1148, 32 slots).
MAX_WANDERERS = 32

_DIRECTION_VALUES = (Direction.WEST, Direction.NORTH, Direction.EAST, Direction.SOUTH)


def get_relative_direction_mask(
    width: int, height: int, to_x: int, to_y: int, from_x: int, from_y: int
) -> int:
    """Java ``util/Utils.java:359-401`` ``getRelativeDirection`` — the mask of
    directions leading from (from_x, from_y) toward (to_x, to_y), with the
    same wrap adjustments the Java helper applies (which, as there, reuse
    ``width`` for the Y axis)."""

    def _shortest(f: int, t: int, span: int) -> int:
        if abs(f - t) > abs(f + span - t):
            return f + span
        if abs(f - t) > abs(f - span - t):
            return f - span
        return f

    from_x = _shortest(from_x, to_x, width)
    # Java quirk (Utils.java:371-376 / 328-332): the Y wrap compares against
    # width-sized shifts but shifts by height — identical outcomes on square
    # maps, so this port compares and shifts with width for both axes.
    from_y = _shortest(from_y, to_y, width)

    dirmask = 0
    dx = from_x - to_x
    dy = from_y - to_y
    if dx < 0:
        dirmask |= Direction.EAST.mask
    elif dx > 0:
        dirmask |= Direction.WEST.mask
    if dy < 0:
        dirmask |= Direction.SOUTH.mask
    elif dy > 0:
        dirmask |= Direction.NORTH.mask
    return dirmask


def movement_distance(
    width: int, height: int, from_x: int, from_y: int, to_x: int, to_y: int
) -> int:
    """Java ``util/Utils.java:314-357`` ``movementDistance`` — the directional
    walk-step count between two tiles over the wrap seams."""

    def _shortest(f: int, t: int, span: int) -> int:
        if abs(f - t) > abs(f + span - t):
            return f + span
        if abs(f - t) > abs(f - span - t):
            return f - span
        return f

    from_x = _shortest(from_x, to_x, width)
    # Java quirk (Utils.java:328-332): compares against width, shifts by
    # height — equal outcomes on square maps; width is used for both here.
    from_y = _shortest(from_y, to_y, width)

    dirmask = get_relative_direction_mask(width, height, to_x, to_y, from_x, from_y)

    dist = 0
    while from_x != to_x or from_y != to_y:
        if from_x != to_x:
            from_x = from_x - 1 if dirmask & Direction.WEST.mask else from_x + 1
            dist += 1
        if from_y != to_y:
            from_y = from_y - 1 if dirmask & Direction.NORTH.mask else from_y + 1
            dist += 1
    return dist


def direction_by_mask(mask: int) -> Direction | None:
    """Java ``Constants.java:360-368`` ``getByMask`` — the single direction
    matching an exactly-one-bit mask."""
    for d in _DIRECTION_VALUES:
        if d.mask == mask:
            return d
    return None


def random_valid_direction(mask: int) -> Direction | None:
    """Java ``Constants.java:319-333`` ``getRandomValidDirection`` — a random
    direction among the masked set, value order."""
    valid = [d for d in _DIRECTION_VALUES if mask & d.mask]
    if not valid:
        return None
    return random.choice(valid)


def can_creature_move_on(tile, creature) -> bool:
    """Java ``objects/BaseMap.java:700-717`` ``canCreatureMoveOn``."""
    if creature.sails:
        return bool(tile.attribs & TileAttrib.SAILABLE)
    if creature.swims:
        return bool(tile.attribs & TileAttrib.SWIMMABLE)
    if creature.flies:
        return not bool(tile.attribs & TileAttrib.UNFLYABLE)
    if bool(tile.attribs & TileAttrib.CREATUREUNWALKABLE):
        return False
    return creature.incorporeal or not bool(tile.attribs & TileAttrib.UNWALKABLE)


def has_ship_object_at(party, x: int, y: int) -> bool:
    """Java ``objects/BaseMap.java:786-793`` ``hasShipObjectAt`` — a frigate
    object sits on that tile. Java matches a tile carrying TileRule.ship;
    "frigate" is the only rule-"ship" tile (tileset-base.xml:13), so the
    exact name equals the rule check."""
    return any(
        str(obj.get("tile", "")).lower() == "frigate"
        and obj.get("x") == x
        and obj.get("y") == y
        for obj in party.dynamic_objects
    )



# --- Overworld HUD sky strip (Java GameScreen.java:180-196) ------------------ #
# On Sosaria (map id 0) Java draws two moon-phase icons (Trammel and Felucca),
# the "Wind <direction>" text, the aura label while active, and "Hull: N" when
# on a ship. Port adaptation (documented per the strip ruling): the phase atlas
# icons become clipped circle-with-shadow EGA glyphs and the wind/aura text
# keeps the port's font-drawn text style. Hull is NOT duplicated here — the
# stats panel transport row already carries "SHIP (HULL:n)".
# User ruling 2026-11-22: the wind reads "Wind NORTH" etc., no arrow glyph.

# The 5 wind outcomes of a re-roll (4 directions + the becalmed None):
# GBC menucmd3.c:1449-1467 picks among directions plus calm and never
# repeats the outgoing value.
WIND_OUTCOMES: list["Direction | None"] = [
    Direction.NORTH,
    Direction.SOUTH,
    Direction.EAST,
    Direction.WEST,
    None,
]


def sky_strip_texts(
    wind_direction: "Direction | None",
    trammel_phase: int,
    felucca_phase: int,
    aura: "AuraType | None" = None,
) -> list[str]:
    """Text lines of the sky strip (wind + moons, plus the aura label first
    when active — Java GameScreen.java:184,188-189). USER-DIRECTED GBC-RULES
    DEVIATION (2026-11-14): a None (becalmed) wind displays as "Wind CALM"
    with no arrow."""
    texts: list[str] = []
    if aura is not None and aura != AuraType.NONE:
        texts.append(aura.name)
    if wind_direction is None:
        texts.append("Wind CALM")
    else:
        texts.append(f"Wind {wind_direction.name}")
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
        # The wind is move-driven now (Task 20, USER-DIRECTED GBC-RULES
        # DEVIATION 2026-11-14: re-roll per 20 consumed moves) — like the
        # moon clock the wall-clock timer block is gone from here; see
        # _finish_turn / _reroll_wind.

        self.world_renderer = (
            WorldRenderer(asset_mgr) if asset_mgr is not None else None
        )
        self.stats_panel = StatsPanel(asset_mgr=self.asset_mgr)
        self.text_log = TextLog(max_lines=5, wrap_width=64)

        self.cannon_fx: list[dict[str, Any]] = []
        # LairWare shrine (world.shrine): the member at the shrine while its
        # picture is up, and the picture itself (loaded on first use).
        self.shrine_member: int | None = None
        self._shrine_image: pygame.Surface | None = None


        raw_id = getattr(self.game_map, "id", None)
        if raw_id is None:
            raw_id = self.map_id
        lookup_id: int | None = None
        if raw_id is not None:
            try:
                lookup_id = int(raw_id)
            except (TypeError, ValueError):
                lookup_id = MAP_NAME_TO_ID.get(str(raw_id).upper())
        label = (
            MAP_ID_TO_LABEL.get(lookup_id)
            if lookup_id is not None
            else None
        ) or getattr(self.game_map, "name", "Sosaria")
        self.text_log.add_message(f"Entering {label}!")
        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): the wind can be
        # becalmed (None) — the entry message names the calm instead of
        # crashing on a missing direction name.
        if self.party.wind_direction is None:
            self.text_log.add_message("The wind is calm.")
        else:
            self.text_log.add_message(
                f"Wind blows {self.party.wind_direction.name}."
            )

    @property
    def moon_phase(self) -> int:
        """The combined 0..23 celestial phase, hosted on the party record so
        the move-driven clock (and its save round-trip) lives in one place."""
        return self.party.moon_phase

    @moon_phase.setter
    def moon_phase(self, val: int) -> None:
        self.party.moon_phase = val % 24

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
        """Sosaria and Ambrosia. LairWare ShowWind (UltimaMain.c:3305-3340)
        hides the wind only in dungeons and combat, and ValidTrans applies it
        to every ship, Ambrosia included (user report 2026-11-22: the wind
        steered there unseen). Java gated the HUD on Sosaria only."""
        return str(self.map_id) in ("0", "13")

    @property
    def moons_shown(self) -> bool:
        """Sosaria only: LairWare MoonGateUpdate (UltimaMisc.c:1489-1491)
        runs only on the surface."""
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
            surface.blit(f.render(aura.name, True, EGA_YELLOW), (margin, y))
            y += f.get_linesize()

        wind = self.party.wind_direction
        wind_txt = (
            "Wind CALM"
            if wind is None
            else f"Wind {wind.name}"
        )
        surface.blit(f.render(wind_txt, True, EGA_LIGHT_GRAY), (margin, y))

        size = 2 * radius + 3
        gx2 = pane_right - margin - radius - 2
        gx1 = gx2 - radius - 1 - size
        if not self.moons_shown:
            return
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

        # Parked ships/horses belong to the map they were left on (LairWare
        # Push/PullSosaria; see Party.enter_surface_map).
        try:
            surface_id = int(self.map_id)
        except (TypeError, ValueError):
            surface_id = -1
        if hasattr(self.party, "enter_surface_map"):
            self.party.enter_surface_map(surface_id)
        if surface_id == 13:
            self._load_ambrosia_monsters()

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
        self._seed_wanderers()

    # LairWare monster tile index (Tiles.plist) -> creatures.xml tile key, for
    # the monster table Ambrosia loads with its map.
    _AMBROSIA_MONSTER_TILES: dict[int, str] = {
        10: "horse", 13: "serpent", 14: "squid", 15: "pirate", 16: "merchant",
        17: "jester", 18: "guard", 20: "fighter", 21: "cleric", 22: "wizard",
        23: "thief", 24: "orc", 25: "skeleton", 26: "giant", 27: "daemon",
        28: "pincher", 29: "dragon", 30: "balron",
    }

    def _load_ambrosia_monsters(self) -> None:
        """Ambrosia's monster table as live monsters.

        LairWare loads Ambrosia's 'MONS' resource with its map on every visit
        (LoadUltimaMap(421), UltimaMisc.c:861-901), so these monsters are back
        at their start tiles each time. On Ambrosia MoveMonsters takes the
        per-monster behaviour byte (UltimaMisc.c:1276-1330); every Ambrosia
        entry has 0xC0, which is ``goto moveoutside``: the Sosaria behaviour
        (close in, attack, pirates fire broadsides). A pirate fought from land
        leaves its ship (AttackCode, UltimaMain.c:1355-1357) — the only way
        off Ambrosia (the whirlpool takes only a ship). The port loaded them
        as frozen town people (Ambrosia is a "city" map in maps.xml); they
        move to the creature list here. Horse and jester keep the port's
        creature definitions (non-attacking).
        """
        if self.game_map is None:
            return
        keep = []
        for npc in list(getattr(self.game_map, "npcs", ()) or ()):
            key = self._AMBROSIA_MONSTER_TILES.get(getattr(npc, "tile_index", -1))
            if key is None:
                keep.append(npc)
                continue
            c_def = self.asset_mgr.get_creature(key) if self.asset_mgr else None
            self.creatures.append({
                "name": (c_def.name if c_def else key.capitalize()),
                "tile_name": key,
                "tile": key,
                "x": npc.x,
                "y": npc.y,
            })
        self.game_map.npcs = keep

    def _seed_wanderers(self) -> None:
        """Populate a freshly prepared outdoor map with wanderers.

        USER-DIRECTED DEVIATION FROM JAVA (2026-11-21, original-game
        spawning): the LairWare new-game path runs ``SpawnMonster()`` 500
        times (refs/ultima3/Sources/UltimaMain.c:2055-2058). Each call keeps
        its 7/135 rate gate, so a fresh map starts with ~26 of the 32 slots
        filled, scattered over the whole map.
        """
        if not self.random_encounters_enabled or self.game_map is None:
            return
        if str(self.map_id) != "0":
            return  # SpawnMonster runs on Sosaria only (UltimaMisc.c:1144)
        for _ in range(500):
            self._spawn_wandering_creature()

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

        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): debug cheat harness
        # (GBC cheat.c:768-825 docheat) — F10 opens the cheat menu, only
        # when the game runs with --debug. Non-debug F10 stays inert.
        if debug.DEBUG_MODE and event.key == pygame.K_F10:
            debug.open_cheat_menu(self.text_log, self.party)
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
            # LairWare Fire (UltimaMain.c:1523-1528): only aboard a ship;
            # otherwise "Fire <-WHAT?" (What2), and the turn passes.
            if self.party.transport == Transport.SHIP:
                self._prompt_fire_cannons()
            else:
                self.text_log.add_message("Fire <-WHAT?")
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
        """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): VIEDA renders the
        peer-gem view (GBC menucmd.c:1379-1390; LW UltimaSpellCombat.c
        corroboration) through the SAME screen path as the P command —
        dopeergem(1) skips the spell branch's choosechar2 and gem decrement
        (menucmd.c:695-712 runs only for dopeergem(0)), so casting VIEDA
        opens the view without consuming a gem and without the "Peer at a
        Gem!" log. Java's spellView (SpellUtil.java:494-499) likewise hands
        input straight to the peer-gem adapter."""
        # The view owns input and the render override draws the gem picture.
        self.gem_view_active = True

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
                take_chest_object(self.party, px, py, self.game_map)
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
        ``Context.lastShip``.
        """
        # Java GameScreen.java:584-596 — X is silent on foot (it only resets
        # the transport and sets the avatar anim); the keyUp tail still ticks.
        if self.party.transport == Transport.FOOT:
            return

        old_t = self.party.transport
        if old_t == Transport.SHIP and self.game_map is not None:
            on_shoreline = False
            for d in (Direction.NORTH, Direction.SOUTH, Direction.WEST, Direction.EAST):
                nx = (self.party.x + d.dx) % self.game_map.width
                ny = (self.party.y + d.dy) % self.game_map.height
                ntile = self.game_map.get_tile(nx, ny)
                if (
                    ntile is not None
                    and not getattr(ntile, "swimmable", False)
                    and can_move_to(self.game_map, nx, ny, transport=Transport.FOOT, party=self.party)
                ):
                    on_shoreline = True
                    break
            if not on_shoreline:
                self.text_log.add_message("Not on shoreline!")
                return

        self.party.transport = Transport.FOOT
        if old_t == Transport.HORSE:
            self.party.dynamic_objects.append({"tile": "horse", "x": self.party.x, "y": self.party.y})
            self.text_log.add_message("Dismounted horse.")
        else:
            existing = next(
                (
                    obj
                    for obj in self.party.dynamic_objects
                    if str(obj.get("tile", "")).lower() == "frigate"
                    and obj.get("x") == self.party.x
                    and obj.get("y") == self.party.y
                ),
                None,
            )
            if existing is None:
                ship = {"tile": "frigate", "x": self.party.x, "y": self.party.y}
                self.party.dynamic_objects.append(ship)
            else:
                ship = existing
            self.party.last_ship = ship
            self.text_log.add_message("Disembarked frigate.")

    def _board_transport(self) -> None:
        """Board the frigate or horse exactly on the party's tile (Java ``B``).

        Java truth: ``exodus/GameScreen.java:945-979`` ``board(x, y)`` —
        already mounted: "Board: Can't!"; a frigate object with
        ``cx == x && cy == y`` boards (LairWare ships have no hull), then a horse creature on the exact tile
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
            # Java matches the exact tile name: `"frigate".equals(
            # d.getTile().getName())` (GameScreen.java:955) — no "ship"
            # superset ("ship" is not a tile name Java can match).
            if tile == "frigate" and obj.get("x") == px and obj.get("y") == py:
                self.party.dynamic_objects.pop(idx)
                self.party.transport = Transport.SHIP
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
        """NEGATE TIME: consume the FIRST member's powder for a QUICKNESS aura
        (Java GameScreen.java:1089-1100 negateTime). The duration is 10 per
        USER-DIRECTED GBC-RULES DEVIATION (2026-11-14) (GBC battle2.c:722-733;
        LW UltimaMain.c:2129-2139) — superseding the old 6-turn reading."""
        for m in self.party.members:
            if getattr(m, "powder", 0) > 0:
                m.powder -= 1
                self.text_log.add_message("Stop time with a powder!")
                self.party.aura.set(AuraType.QUICKNESS, 10)
                self._consume_pass_turn()  # Java keyUp tail: N falls through
                return
        self.text_log.add_message("None!")
        self._consume_pass_turn()  # Java keyUp tail: N falls through

    def _prompt_other(self) -> None:
        """Prompt for custom other command (PRAY, BRIBE, STEAL, DIG, etc.).

        USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): functional Other
        command (GBC menucmd3.c:1019-1236; menucmd2.c:1440-1540; LW
        UltimaMisc.c:2262-2503) — both this and the town prompt delegate to
        py_exodus.special_commands so the commands share one implementation.
        KISS is NOT in U3 (K is Klimb; the LW menu lacks it too — user ruling
        2026-11-14): it falls through to the generic "Nothing happened.".
        """
        def _on_other(cmd: str) -> None:
            c = cmd.strip().upper()
            if not c:
                return
            if c == "PRAY":
                self.text_log.add_message(
                    special_commands.do_pray(
                        self.party.x,
                        self.party.y,
                        self.map_id,
                        str(getattr(self.game_map, "name", "") or ""),
                    )
                )
            elif c == "BRIBE":
                special_commands.bribe_flow(
                    self.text_log,
                    self.party,
                    self.party.x,
                    self.party.y,
                    self.game_map,
                    creatures=self.creatures,
                )
            elif c == "STEAL":
                special_commands.steal_flow(
                    self.text_log, self.party, self.party.x, self.party.y, self.game_map
                )
            elif c == "DIG":
                special_commands.dig_flow(
                    self.text_log, self.party, self.party.x, self.party.y, self.game_map
                )
            elif c == "SEARCH":
                special_commands.search_flow(
                    self.text_log, self.party, self.party.x, self.party.y, self.game_map
                )
            elif c == "SCORE":
                self.text_log.add_message(special_commands.do_score(self.party))
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
        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): unlocking consumes one key (GBC menucmd2.c:1595-1650)
        # — the acting member is the member 1-4 the U flow already prompts for,
        # and unlock_door itself checks its keys and spends one ONLY on the
        # locked-door conversion (GBC menucmd2.c:1655-1657; anything else is
        # dounlock's else: no conversion, no spend). A keyless
        # member is refused with "You need a key!" (GBC refusal message).
        tx, ty = self.party.x + d.dx, self.party.y + d.dy
        if door_module.unlock_door(self.game_map, tx, ty, member=member):
            # LairWare Unlock (UltimaMain.c:2428-2433): on the surface the
            # door turns into the tile WEST of it (anything past floor reads
            # as grass). Ambrosia's water door at (39, 61) therefore opens
            # into water and a ship can pass to the whirlpool bay.
            west = self.game_map.get_tile((tx - 1) % self.game_map.width, ty)
            if west is not None and 0 <= getattr(west, "index", 99) <= 8:
                self.game_map.set_tile(tx, ty, west)
            elif self.asset_mgr is not None and self.asset_mgr.tile_defs.get(1):
                self.game_map.set_tile(tx, ty, self.asset_mgr.tile_defs.get(1))
            self.text_log.add_message("Unlocked!")
        else:
            if getattr(member, "keys", 0) <= 0:
                self.text_log.add_message("You need a key!")
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
            # Java SecondaryInputProcessor.java:535-538: empty ENTER keeps the
            # prompt open, while ESC remains available so keyboard players cannot softlock.
            self.text_log.prompt(
                "Yell what? ",
                callback=lambda phrase: self._yell(member, phrase),
                allow_empty=False,
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

        # LairWare ships sail straight off in any direction the wind allows
        # (UltimaMain.c North()/ValidTrans): no turn-to-face press, no heading.

        # Frigate sailing rules
        if self.party.transport == Transport.SHIP:
            # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): wind blocks when
            # becalmed/against headwind; forced re-roll per 20 moves (GBC
            # postexo1.c:1848-1852; menucmd3.c:1449-1467). LW is silent on
            # blocking and NES slows-but-moves, so GBC governs: a becalmed
            # ship cannot sail at all, and sailing into the wind's reverse is
            # refused — both supersede the old slow-down behavior. The move
            # is refused without consuming a turn, like any other blocked
            # step.
            wind = self.party.wind_direction
            if wind is None:
                self.text_log.add_message("The ship is becalmed!")
                return
            if direction == wind.reverse():
                self.text_log.add_message("Headwinds block thy ship!")
                return

        nx = (self.party.x + direction.dx) % self.game_map.width
        ny = (self.party.y + direction.dy) % self.game_map.height

        start_tile = self.game_map.get_tile(self.party.x, self.party.y)

        # Java preMove intercepts the step onto Ambrosia's WHIRLPOOL portal
        # before tile walkability / valid-moves mask checks and ferries the
        # party to a random Sosaria coast tile (GameScreen.java:661-670).
        if portal_entry.step_in_whirlpool_portal(self, nx, ny):
            return

        if can_move_to(self.game_map, nx, ny, transport=self.party.transport, party=self.party):
            # Java exploration movement is never slowed (slowedByTile's only
            # caller is CombatScreen.java:937, combat creatures only) — no
            # speed roll on the 2D move paths.
            self.party.x = nx
            self.party.y = ny
            if self.audio is not None:
                self.audio.play_sfx("walk_normal")

            self._finish_turn(start_tile)

            # Check moongate teleports
            self._check_moongates()

            # Check random encounters
            if self.random_encounters_enabled:
                self._check_random_encounter()
        else:
            # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): force field 99
            # damage to members lacking the Mark of Force; passage only when
            # all marked (GBC postexo1.c:1861-1880). The refused energy-field
            # step strikes the unmarked before the block plays out; no sfx
            # change (the blocked step keeps its usual sound, per Task 20's
            # refusal shape).
            self._apply_force_field_block(nx, ny)
            if self.audio is not None:
                self.audio.play_sfx("blocked")

    def _apply_force_field_block(self, nx: int, ny: int) -> None:
        """Apply the GBC force-field strike to a refused energy-field entry.

        USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): force field 99
        damage to members lacking the Mark of Force; passage only when all
        marked (GBC postexo1.c:1861-1880). The strike is the shared
        ``tile_effects.apply_force_field_strike`` (the movement validator
        fires in any context, town screens included); a wipe raises
        ``PartyDeathException`` from the strike, which this catches and
        routes through the death flow (``check_party_death``) — never
        swallowed without it.
        """
        if self.game_map is None:
            return
        try:
            tile_effects.apply_force_field_strike(
                self.party,
                self.game_map.get_tile(nx, ny),
                self.text_log.add_message,
            )
        except PartyDeathException:
            pass
        self.check_party_death()

    def _reroll_wind(self) -> None:
        """Re-roll the wind to a DIFFERENT outcome every 20th consumed move
        (Party.moves modulo — see _finish_turn for the citation comments).

        GBC's dowinds re-rolls per ~20 moves among the 4 directions plus
        becalmed and never repeats the outgoing value, so the candidate pool
        excludes whatever the wind currently is (a Direction or None).
        """
        current = self.party.wind_direction
        choices = [o for o in WIND_OUTCOMES if o != current]
        self.party.wind_direction = random.choice(choices)

    def _finish_turn(self, effect_tile=None) -> None:
        """End the movement turn: sink check, aura tick, submorsel tick, tile
        effect, then the whirlpool engulf scan.

        Java truth: ``exodus/GameScreen.java:706-754`` ``finishTurn`` —
        ``checkHullIntegrity`` runs first, then turn end runs ``endTurn``,
        ``aura.passTurn`` and applies the tile-rule effect of the tile the
        party occupies at the start of the turn (``getCurrentMapCoords`` is
        captured pre-move, so the effect lands on the tile being left, not
        the one entered); moves and the pass key route through it. The
        whirlpool engulf sits inside ``moveObjects``
        (``BaseMap.java:540-553`` at ``movementDistance`` ≤ 1 — same tile or
        an orthogonal neighbor, no diagonals); ``_check_whirlpool_engulf``
        below supersedes that ring with the ruled same-tile-only contact
        (GBC/LW, 2026-11-14). A wipe raises

        ``PartyDeathException``; the post-check routes the game-over flow
        (Task 2). ``sosaria`` tracks the current map id;
        the 40-submorsel interval is surface maps SOSARIA (0) and EXODUS (2)
        only — Ambrosia (13) drains at 10 (``Party.java:598-600``).
        """
        map_id = str(getattr(self.game_map, "id", self.map_id))
        sosaria = map_id == "0"
        try:
            # Java order (GameScreen.java:710-714): endTurn, then aura.passTurn.
            self.party.end_turn(surface=map_id in ("0", "2"), sosaria=sosaria)
            # USER-DIRECTED ORIGINAL-RULES DEVIATION (2026-11-10): mana
            # (+1/turn surface, Druids double) and poison (-1 HP per turn)
            # run every consumed turn here. HP regen and starvation are
            # meal-bound — USER-DIRECTED GBC-RULES DEVIATION (2026-11-14,
            # supersedes the 2026-11-10 interpretation for these two rules):
            # both ride the meal crossing inside Party.end_turn (GBC
            # funcs5.c:741-789; LW UltimaMisc.c:1428-1493).
            self.party.tick_regen(surface=True)
            # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): moons advance
            # per 4 moves surface / 16 elsewhere; stop-time freezes moons
            # (GBC funcs5.c:1272-1279). Every overland map is the fast
            # (outdoor) cadence here.
            self.party.advance_moons(surface=True)
            # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): wind blocks
            # when becalmed/against headwind; forced re-roll per 20 moves
            # (GBC postexo1.c:1848-1852; menucmd3.c:1449-1467). Move-driven
            # like the moon clock (the 4-second wall-clock timer is gone):
            # every 20th consumed move — Party.moves, the counter end_turn
            # just advanced, GBC's ``moves`` modulo — the wind re-rolls to a
            # DIFFERENT outcome among the 4 directions plus becalmed (GBC
            # dowinds avoids repeating).
            if self.party.moves % 20 == 0:
                self._reroll_wind()
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
        """Sailing onto a whirlpool tile engulfs the party's ship.

        The engulf sequence stays Java's whirlpool branch
        (``objects/BaseMap.java:540-553``): four log lines, transport set to
        FOOT (ship and crew lost), and the party ferried to Ambrosia (32, 54).
        The two Sosaria whirlpools live at (50, 13) and (17, 48)
        (``GameScreen.java:111-121``). Under a QUICKNESS aura
        ``moveObjects`` is skipped entirely (``GameScreen.java:728-731``), so
        no engulf happens while time is quick.
        """
        if self.game_map is None:
            return
        if self.party.aura.get_type() == AuraType.QUICKNESS:
            return
        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): whirlpool engulfs ships only on same-tile contact (GBC ult3.c:2418; LW UltimaMain.c:2959-3003 engulf on tile equality — ships-only per GBC ruling; supersedes Java distance<=1 fan-out)
        for c in self.creatures:
            if c.get("tile_name") != "whirlpool":
                continue
            wx, wy = c.get("x", -99), c.get("y", -99)
            if not (0 <= wx < self.game_map.width and 0 <= wy < self.game_map.height):
                # Whirlpools only exist where they were placed on Sosaria
                # (GameScreen.java:111-121); never engulf from an off-map
                # fixture position.
                continue
            if wx != self.party.x or wy != self.party.y:
                # Same-tile contact only: no wrap-aware distance ring.
                continue
            if self.party.transport == Transport.SHIP:
                if self.audio is not None:
                    self.audio.play_sfx("wave")
                for line in self.ENGULF_LINES:
                    self.text_log.add_message(line)
                self.party.transport = Transport.FOOT
                # LairWare GoWhirlPool saves the engulf spot (Party[4]/[5])
                # and returns the party there (UltimaMain.c:3043-3046, 3093).
                self.party.whirlpool_return = (self.party.x, self.party.y)
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

        self.text_log.prompt("Fire Direct-", callback=_on_dir, single_char=True)

    def _fire_cannons(self, direction: Direction) -> None:
        """LairWare Fire (UltimaMain.c:1523-1580): the shot flies up to three
        tiles in any direction, wrapping round the map, and stops at the
        first monster: half the time it misses silently (a pirate shrugs
        it off half again: Monsters[] holds map values, 0x3C is the Pirate), otherwise the monster is destroyed. Empty ships
        and terrain don't stop it."""
        from py_exodus.world.monster_variants import plural_name

        if self.audio is not None:
            self.audio.play_sfx("cannon") or self.audio.play_sfx("enemy_magic_proj")
        if self.game_map is None:
            return
        cx, cy = self.party.x, self.party.y
        path: list[tuple[int, int]] = []
        hit = False
        for step in range(1, 4):
            tx = (cx + direction.dx * step) % self.game_map.width
            ty = (cy + direction.dy * step) % self.game_map.height
            path.append((tx, ty))
            target = next(
                (c for c in self.creatures if c.get("x") == tx and c.get("y") == ty), None
            )
            if target is None:
                continue
            tile_name = str(target.get("tile_name") or target.get("tile") or "").lower()
            if tile_name == "pirate" and random.randint(0, 255) < 128:
                break
            if random.randint(0, 255) < 128:
                break
            self.creatures.remove(target)
            name = plural_name(tile_name, int(target.get("variant", 0) or 0))
            self.text_log.add_message(f"{name} destroyed!")
            hit = True
            break

        if path:
            self.cannon_fx.append(
                {
                    "start_pos": (cx, cy),
                    "path": path,
                    "target_pos": path[-1],
                    "hit": hit,
                    "duration": 0.35,
                    "timer": 0.35,
                }
            )

    def begin_shrine(self) -> None:
        """LairWare Enter on an Ambrosia shrine: "Who enters?-" (1-4)."""
        from py_exodus.world import shrine

        self.text_log.add_message(shrine.MSG_WHO)
        self.text_log.prompt(shrine.PROMPT_WHO, callback=self._shrine_who, single_char=True)

    def _shrine_who(self, ch: str) -> None:
        from py_exodus.world import shrine

        idx = int(ch) - 1 if ch in ("1", "2", "3", "4") else -1
        member = self.party.get_member(idx) if 0 <= idx < len(self.party.members) else None
        if member is None:
            if self.audio is not None:
                self.audio.play_sfx("blocked")
            return
        if member.is_disabled():  # LairWare CheckAlive: Good or Poisoned only
            self.text_log.add_message(shrine.MSG_INCAP)
            return
        self.shrine_member = idx
        self.text_log.add_message(shrine.welcome(shrine.shrine_stat(self.party.x)))
        self.text_log.prompt(
            shrine.PROMPT_OFFER, callback=self._shrine_offer, single_char=True,
            on_cancel=self._shrine_close,
        )

    def _shrine_offer(self, ch: str) -> None:
        from py_exodus.world import shrine

        if not ch.isdigit():  # LairWare waits for a digit
            self.text_log.prompt(
                shrine.PROMPT_OFFER, callback=self._shrine_offer, single_char=True,
                on_cancel=self._shrine_close,
            )
            return
        member = self.party.get_member(self.shrine_member or 0)
        msg = shrine.offer(self.party, member, shrine.shrine_stat(self.party.x), int(ch))
        self.text_log.add_message(msg)
        if self.audio is not None:
            self.audio.play_sfx("Shrine.wav" if msg == shrine.MSG_SHAZAM else "blocked")
        self._shrine_close()

    def _shrine_close(self) -> None:
        self.shrine_member = None

    def _render_shrine_image(self, surface: pygame.Surface, size: int) -> None:
        """LairWare ImageDisplay(7): Shrine.jpg over the map while a member
        is at the shrine."""
        if self.shrine_member is None or self.asset_mgr is None:
            return
        if self._shrine_image is None:
            from py_exodus.assets import load_image_surface

            try:
                self._shrine_image = load_image_surface(
                    self.asset_mgr.resolve_path("graphics", "lairware", "shrine.jpg")
                )
            except (FileNotFoundError, pygame.error):
                return
        surface.blit(pygame.transform.smoothscale(self._shrine_image, (size, size)), (0, 0))

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
        """Check if party stepped onto the visible moongate (site[slow moon]).

        USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): moongate model per
        refs — one visible gate at the slow-moon site, entry teleports to the
        fast-moon site (GBC funcs5.c:1134-1152; LW UltimaMisc.c:1511-1560;
        NES Bank0F MoonGateTbl:734-771). The 8 fixed gate sites ARE the
        destination table: the gate is visible at site[trammel_phase] (the
        SLOW moon) and stepping on it repositions the party to
        site[felucca_phase] (the FAST moon) — GBC teleportsscreenx/y from
        moongates[(moon2<<1)] — replacing the per-gate d1/d2/d3 tables (a
        Java invention the refs do not have). Same-map teleport, overworld
        only; Dawn's double-new-moon portal rule is separate (portal_entry).
        """
        if self.game_map is None:
            return

        # Only the slow-moon site is active (GBC moon1 gate; funcs5.c:1134-1152).
        active_gate = None
        for gate in self.game_map.moongates:
            if gate.phase == self.trammel_phase:
                active_gate = gate
                break

        if active_gate is None:
            return

        if active_gate.x == self.party.x and active_gate.y == self.party.y:
            # Destination is site[fast moon]; equal moons means the gate
            # teleports to itself, i.e. nothing happens.
            dest_gate = None
            for g in self.game_map.moongates:
                if g.phase == self.felucca_phase:
                    dest_gate = g
                    break
            if dest_gate is None or dest_gate is active_gate:
                return

            self.party.x = dest_gate.x
            self.party.y = dest_gate.y
            self.text_log.add_message("Stepped through mystical moongate!")
            if self.audio is not None:
                self.audio.play_sfx("moongate_flash")

    def _spawn_wandering_creature(self) -> None:
        """One call of the original ``SpawnMonster`` (once per turn).

        USER-DIRECTED DEVIATION FROM JAVA (2026-11-21, user ruling: wanderer
        spawning must be faithful to the ORIGINAL game). LairWare
        refs/ultima3/Sources/UltimaMisc.c:1141-1186 ($7A0C):

        - rate: ``if (RandNum(0, 134) < 128) return;`` -> 7/135 per turn;
        - population: 32 monster slots (whirlpool fixtures are not slots);
        - placement: a RANDOM tile anywhere on the map, never in the party's
          column or row; the tile must show the rolled type's start terrain
          (``_pick_creature_for_tile``). A failed pick moves on to the next
          free slot (``goto spawn``), so the number of tries equals the
          number of free slots.

        Port guards kept: never onto another creature or a portal (the
        original's monsters live in the map grid, so a monster tile is never
        the start terrain of another one, and portals are not grass/water).
        Java's 8..12-tile ring, forced spawn and distance despawn are gone.
        """
        if self.game_map is None:
            return
        # LairWare SpawnMonster: ``if (Party[3] != 0) return;`` — no
        # wanderers on Ambrosia (UltimaMisc.c:1144-1145).
        if str(self.map_id) != "0":
            return
        if random.randint(0, 134) < 128:
            return

        free_slots = MAX_WANDERERS - sum(
            1 for c in self.creatures if c.get("tile_name") != "whirlpool"
        )
        width, height = self.game_map.width, self.game_map.height
        portal_coords = {(p.x, p.y) for p in getattr(self.game_map, "portals", ())}
        occupied = {(c.get("x"), c.get("y")) for c in self.creatures}
        for _ in range(max(0, free_slots)):
            sx = random.randint(0, width - 1)
            if sx == self.party.x:
                continue
            sy = random.randint(0, height - 1)
            if sy == self.party.y:
                continue
            if (sx, sy) in occupied or (sx, sy) in portal_coords:
                continue

            tile = self.game_map.get_tile(sx, sy)
            if tile is None:
                continue

            c_name = self._pick_creature_for_tile(tile)
            if c_name is None:
                continue

            c_def = self.asset_mgr.get_creature(c_name) if self.asset_mgr else None
            # LairWare SpawnMonster (UltimaMisc.c:1181-1185): a variant,
            # named for the Thief..Balron (Brigand, Goblin, Devil...).
            variant = roll_variant()
            self.creatures.append({
                # Display name from creatures.xml (e.g. "Man-O-War" for the
                # squid tile), or the variant's own name.
                "name": variant_name(c_name, variant)
                or (c_def.name if c_def else c_name.capitalize()),
                "tile_name": c_name,
                "tile": c_name,
                "variant": variant,
                "x": sx,
                "y": sy,
                # Java Creature.sailDir defaults to EAST (Creature.java:63).
                **({"sail_dir": "EAST"} if c_name == "pirate" else {}),
            })
            return

    # USER-DIRECTED DEVIATION FROM JAVA (2026-11-21, user ruling: wanderer
    # spawning must be faithful to the ORIGINAL game). Java's
    # getRandomCreatureForTile (health tiers + an exclusive-bound bug) never
    # spawned Pincher, Dragon, Balron or Man-O-War (Squid) and invented
    # party-strength tiers the original does not have. This is the original's
    # SpawnMonster (LairWare refs/ultima3/Sources/UltimaMisc.c:1141-1186,
    # $7A0C; table at :36-37; tile names refs/ultima3/Resources/English.lproj/
    # Strings/Tiles.plist):
    #   type = RandNum(0,12) & RandNum(0,12)            (inclusive bounds;
    #          the bitwise AND skews hard to low types: Orc 42%, Thief and
    #          Skeleton 12.4% each, Giant/Wizard 10.1%, Fighter 4.1%, Daemon,
    #          Serpent, Man-O-War, Pirate 1.8% each, Pincher/Dragon/Balron
    #          0.6% each)
    #   if EVERY member's max HP <= 150: type = RandNum(0,2) (Orc/Thief/Skeleton)
    # and the picked tile must already show the type's start terrain
    # (MonBegin): land types only on plain grass, sea types only on water;
    # otherwise the spawn attempt fails and spawnCreature retries elsewhere.
    # Entries: (creatures.xml id, needs_water).
    _ORIGINAL_SPAWN_TABLE: tuple[tuple[int, bool], ...] = (
        (10, False),  # 0  Orc
        (12, False),  # 1  Thief
        (11, False),  # 2  Skeleton
        (15, False),  # 3  Fighter
        (13, False),  # 4  Giant
        (14, False),  # 5  Daemon
        (21, True),   # 6  Sea Serpent
        (17, False),  # 7  Pincher (variants Snatch, Bradle)
        (16, False),  # 8  Wizard
        (22, True),   # 9  Man-O-War (Squid)
        (20, True),   # 10 Pirate
        (18, False),  # 11 Dragon (variants Griffon, Wyvern)
        (19, False),  # 12 Balron (variants Orcus, Devil)
    )

    def _pick_creature_for_tile(self, tile) -> str | None:
        """Original SpawnMonster type roll + terrain check (see table above).

        Returns the creatures.xml tile key, or None when the rolled type does
        not suit the tile (the caller re-tries another tile).
        """
        if self.asset_mgr is None:
            return None

        if bool(getattr(tile, "attribs", 0) & TileAttrib.CREATUREUNWALKABLE):
            return None

        members = self.party.members
        if members and all(m.max_hp <= 150 for m in members):
            idx = random.randint(0, 2)
        else:
            idx = random.randint(0, 12) & random.randint(0, 12)
        cid, needs_water = self._ORIGINAL_SPAWN_TABLE[idx]
        if needs_water:
            if not tile.swimmable:
                return None
        elif tile.swimmable or str(getattr(tile, "name", "")).lower() != "grass":
            return None

        for c_def in self.asset_mgr.creatures.values():
            if c_def.id == cid:
                return c_def.tile.lower()
        return None

    def _update_creatures(self) -> None:
        """Java ``objects/BaseMap.java:421-610`` ``moveObjects`` creature half.

        The QUICKNESS aura skips ``moveObjects`` for the turn
        (``GameScreen.java:728-731``). Per creature, in Java's order:

        1. No distance despawn: Java removes creatures beyond 24 tiles
           (BaseMap.java:505-509); the original keeps them (user-directed
           original-game spawning, 2026-11-21).
        2. Pirate broadsides (BaseMap.java:511-538): with the avatar in the
           same row/column, range 2-3 on a broadsides heading fires the enemy
           cannons (and eats the tick); 2-3 misaligned turns to a broadsides
           heading 1-in-2; distance <= 1 battles when aligned, else turns.
        3. Distance <= 1 for other creatures: attack-capable ones ENGAGE
           (battle, creature removed) — engagement is by proximity, not
           same-tile contact; wontattack creatures (whirlpools included)
           never battle — the whirlpool engulf scan in ``_finish_turn``
           carries Java's 542-553 engulf branch.
        4. Movement inside ``getValidMovesMask`` (BaseMap.java:633-717):
           wontattack creatures random-walk, attackers path toward the
           avatar; a zero intersection means no move this tick. PIRATES obey
           the rotate-then-move rule (BaseMap.java:573-578): sailing only
           when the intended dir equals ``sail_dir``, else the turn consumes
           the tick.
        """
        # Original FinishAll (UltimaMisc.c:1111-1126): SpawnMonster then
        # MoveMonsters every turn; the 7/135 gate lives in the spawn call.
        if self.random_encounters_enabled:
            self._spawn_wandering_creature()

        # Java GameScreen.java:728-731 — moveObjects is skipped entirely
        # while a QUICKNESS aura is active.
        if self.party.aura.get_type() == AuraType.QUICKNESS:
            return

        if self.game_map is None:
            return
        width = self.game_map.width
        height = self.game_map.height

        survivors: list[dict[str, Any]] = []
        encounter_creature: dict[str, Any] | None = None
        engaged = False
        snapshot = list(self.creatures)

        for i, c in enumerate(snapshot):
            tile_name = str(c.get("tile_name", ""))
            cx, cy = c["x"], c["y"]

            cr_def = (
                self.asset_mgr.get_creature(tile_name)
                if self.asset_mgr is not None
                else None
            )
            wontattack = (
                cr_def.wontattack if cr_def is not None else bool(c.get("wontattack"))
            )

            # 1. Java despawns beyond MAX_CREATURE_DISTANCE; the original
            # keeps every monster on the map until it dies (USER-DIRECTED
            # DEVIATION, original-game spawning, 2026-11-21).
            dist = movement_distance(width, height, cx, cy, self.party.x, self.party.y)

            # 3. Hostile creatures: engage at distance <= 1 (BaseMap.java:540-558).
            if dist <= 1 and not wontattack:
                encounter_creature = c
                # Java 557 attackAt + break — see above.
                self.creatures = survivors + snapshot[i + 1:]
                engaged = True
                break

            # 4. LairWare MoveMonsters (UltimaMisc.c:1191-1236, user ruling
            # 2026-11-22): a hostile non-pirate tries the diagonal step toward
            # the party, then the vertical one, then the horizontal one; a
            # diagonal step onto the party starts the fight. Java's cardinal-
            # only step left monsters snagged on terrain for good, and since
            # the original never despawns, 32 snagged monsters stopped all
            # spawning (seed 3 starved grinding near Britain).
            if not wontattack:
                step = self._lw_monster_step(c, cr_def, width, height)
                if step == "attack":
                    encounter_creature = c
                    self.creatures = survivors + snapshot[i + 1:]
                    engaged = True
                    break
                if step is not None:
                    c["x"], c["y"] = step
                survivors.append(c)
                # LairWare moveshoot: pirates fire, dragons breathe.
                if tile_name in self.LW_SHOOTERS and not self.party.exodus_defeated:
                    self._lw_monster_shoot(c)
                continue

            # Movement inside the valid-moves mask (BaseMap.java:562-608).
            mask = self._creature_valid_moves_mask(c, cr_def, wontattack)
            if wontattack:
                move_dir = random_valid_direction(mask)
            else:
                toward = get_relative_direction_mask(
                    width, height, self.party.x, self.party.y, cx, cy
                )
                toward &= mask
                if toward > 0:
                    move_dir = random_valid_direction(toward)
                else:
                    move_dir = None  # Java getPath null → no move this tick
            if move_dir is None:
                survivors.append(c)
                continue

            c["x"] = cx + move_dir.dx
            c["y"] = cy + move_dir.dy
            if self.game_map.border_behavior == "wrap":
                c["x"] %= width
                c["y"] %= height
            else:
                c["x"] = max(0, min(width - 1, c["x"]))
                c["y"] = max(0, min(height - 1, c["y"]))

            survivors.append(c)

        if not engaged:
            self.creatures = survivors

        if encounter_creature is not None:
            # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): debug cheat
            # harness (GBC cheat.c:414-825) — NOFIGHT: no random battles; the
            # creature-contact engagement resolves without entering combat
            # (the engaged creature is still consumed by the contact scan).
            if not debug.CHEATS.nofight:
                self._trigger_combat(
                    encounter_creature.get("tile_name", "orc"), encounter_creature
                )

    def _lw_monster_step(self, c: dict[str, Any], cr_def, width: int, height: int):
        """LairWare GetMonsterDir + MoveMonsters: the step toward the party
        (shortest way over the wrap seams, as LW's byte-wrapped delta * 4
        sign gives), trying (dx, dy), then (0, dy), then (dx, 0). Returns
        "attack" when the first step lands on the party, the new (x, y), or
        None (stays put)."""
        wrap = self.game_map.border_behavior == "wrap"

        def heading(delta: int, span: int) -> int:
            if wrap:
                delta = ((delta + span // 2) % span) - span // 2
            return (delta > 0) - (delta < 0)

        cx, cy = c["x"], c["y"]
        dx = heading(self.party.x - cx, width)
        dy = heading(self.party.y - cy, height)

        def norm(x: int, y: int) -> tuple[int, int]:
            if wrap:
                return x % width, y % height
            return max(0, min(width - 1, x)), max(0, min(height - 1, y))

        first = norm(cx + dx, cy + dy)
        if first == (self.party.x, self.party.y):
            return "attack"
        for sx, sy in ((dx, dy), (0, dy), (dx, 0)):
            if sx == 0 and sy == 0:
                continue
            tx, ty = norm(cx + sx, cy + sy)
            if (tx, ty) == (cx, cy) or (tx, ty) == (self.party.x, self.party.y):
                continue
            if self._creature_can_enter(c, cr_def, tx, ty):
                return (tx, ty)
        return None

    def _creature_can_enter(self, c: dict[str, Any], cr_def, tx: int, ty: int) -> bool:
        """One tile of the valid-moves test: terrain, no portal, no other
        creature, not the party's tile unless the creature may step on it."""
        if cr_def is None:
            return False
        if (tx, ty) in {(p.x, p.y) for p in getattr(self.game_map, "portals", ())}:
            return False
        tile = self.game_map.get_tile(tx, ty)
        if tile is None or not can_creature_move_on(tile, cr_def):
            return False
        if tx == self.party.x and ty == self.party.y and not cr_def.can_move_onto_avatar:
            return False
        return not any(
            other is not c and other.get("x") == tx and other.get("y") == ty
            for other in self.creatures
        )

    def _creature_valid_moves_mask(self, c: dict[str, Any], cr_def, wontattack: bool) -> int:
        """Java ``objects/BaseMap.java:637-698`` ``getValidMovesMask`` for a
        creature: each direction passes ``canCreatureMoveOn`` (rule-based
        sailable/swimmable/unwalkable gating), never steps onto the avatar's
        tile unless the creature can move onto the avatar, and never onto a
        tile another creature occupies (``hasBlockingCreatureAt``).
        """
        # deferred (review minors): Java's mask also excludes tiles held by
        # map people (hasBlockingPersonAt, BaseMap.java:746-760) — the
        # Sosaria creature map carries no people, so this is inert here.
        mask = 0
        if self.game_map is None or cr_def is None:
            return mask
        wrap = self.game_map.border_behavior == "wrap"
        portal_coords = {(p.x, p.y) for p in getattr(self.game_map, "portals", ())}
        for d in _DIRECTION_VALUES:
            tx = c["x"] + d.dx
            ty = c["y"] + d.dy
            if not wrap and not (
                0 <= tx < self.game_map.width and 0 <= ty < self.game_map.height
            ):
                # Off-map: Java adds the direction only for fleeing monsters.
                continue
            tx %= self.game_map.width
            ty %= self.game_map.height
            if (tx, ty) in portal_coords:
                continue
            tile = self.game_map.get_tile(tx, ty)
            if tile is None:
                continue
            canmove = can_creature_move_on(tile, cr_def)
            if (
                tx == self.party.x
                and ty == self.party.y
                and not cr_def.can_move_onto_avatar
            ):
                canmove = False
            if any(
                other is not c and other.get("x") == tx and other.get("y") == ty
                for other in self.creatures
            ):
                canmove = False
            if canmove:
                mask |= d.mask
        return mask

    # LairWare map values 0x3C and 0x74 (UltimaMisc.c:1224, 1242).
    LW_SHOOTERS = ("pirate", "dragon")
    # GetXY values 0x08, 0x46, 0x48 stop the shot (screen tiles, tile * 2).
    LW_SHOT_BLOCKERS = ("mountains", "wall", "blank")

    def _lw_monster_shoot(self, c: dict[str, Any]) -> None:
        """LairWare moveshoot (UltimaMisc.c:1245-1278): half the time a pirate
        or dragon in the 11x11 view fires toward the party, each axis
        stepping toward it on its own (so diagonals too), up to 3 tiles,
        stopped by mountains, walls and the void. Reaching the party is
        BombTrap (UltimaMain.c:1728): every living member loses
        (rand & 0x77) + 8 hit points."""
        if random.randint(0, 255) > 127:
            return
        rx, ry = self.party.x - c["x"], self.party.y - c["y"]
        if abs(rx) > 5 or abs(ry) > 5:  # off the 11x11 screen
            return
        dx, dy = (rx > 0) - (rx < 0), (ry > 0) - (ry < 0)
        if self.audio is not None:
            self.audio.play_sfx("Shoot.wav")
        w, h = self.game_map.width, self.game_map.height
        x, y = c["x"], c["y"]
        path: list[tuple[int, int]] = []
        hit = False
        for _ in range(3):
            x, y = x + dx, y + dy
            if abs(self.party.x - x) > 5 or abs(self.party.y - y) > 5:
                break
            tile = self.game_map.get_tile(x % w, y % h)
            if getattr(tile, "name", tile) in self.LW_SHOT_BLOCKERS:
                break
            path.append((x % w, y % h))
            if (x, y) == (self.party.x, self.party.y):
                hit = True
                self._lw_bomb_party()
                break
        if path:
            self.cannon_fx.append({"start_pos": (c["x"], c["y"]), "path": path,
                                   "target_pos": path[-1], "hit": hit,
                                   "duration": 0.35, "timer": 0.35})

    def _lw_bomb_party(self) -> None:
        for m in self.party.members:
            if m.is_disabled():  # CheckAlive
                continue
            if self.audio is not None:
                self.audio.play_sfx("Hit.wav")
            m.apply_damage((random.randint(0, 255) & 0x77) + 8, True)
            if m.hp < 1 and not m.is_dead():  # HPSubtract: under 1 is dead
                m.status = Status.DEAD
        self.check_party_death()

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
        if c_tile not in ("orc", "skeleton", "giant", "thief", "daemon", "fighter", "wizard", "pincher", "dragon", "balron", "pirate", "serpent", "squid"):
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
                creature_variant=int((creature or {}).get("variant", 0) or 0),
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
        saved_monsters = world_state.get("monsters")
        if not isinstance(saved_monsters, list) or not saved_monsters:
            return
        # The block owns the whirlpool fixtures at load: drop the free
        # re-seed before restoring, so the saved fixtures replace them
        # (no duplicates).
        # The saved block also replaces the freshly seeded wanderers
        # (original-game seeding in _seed_wanderers).
        self.creatures = []
        for m in saved_monsters[:8]:
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
                # Fixture whirlpools carry the wontattack flag for saves
                # without a creatures.xml-backed asset manager: they never
                # attack, only random-walk over water (BaseMap.java:564-565).
                creature["wontattack"] = True
            if m.get("hp") is not None:
                creature["hp"] = int(m["hp"])
            if m.get("variant"):
                creature["variant"] = int(m["variant"])
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
                    if c.get("variant"):
                        entry["variant"] = int(c["variant"])
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
            self.anim_frame = (self.anim_frame + 1) % 16  # LW scrolls water in 16 steps

        # The moon phase is move-driven — Party.advance_moons runs from
        # _finish_turn per consumed turn (GBC funcs5.c:1272-1279) — and the
        # wind is move-driven too (Task 20: re-roll per 20 consumed moves
        # out of _finish_turn), so both wall-clock timer blocks are gone.
        self.party.moons = self.moons

        if self.cannon_fx:
            remaining_fx: list[dict[str, Any]] = []
            for fx in self.cannon_fx:
                fx["timer"] -= dt
                if fx["timer"] > 0:
                    remaining_fx.append(fx)
            self.cannon_fx = remaining_fx

    def _render_cannon_fx(self, surface: pygame.Surface) -> None:
        """Render active cannonball projectiles and hit/splash effects."""
        if not self.cannon_fx or self.game_map is None:
            return
        half = 5
        wrap = self.game_map.border_behavior == "wrap"
        map_w, map_h = self.game_map.width, self.game_map.height

        def _to_px(wx: int, wy: int) -> tuple[int, int]:
            dx = wx - self.party.x
            dy = wy - self.party.y
            if wrap:
                if dx > map_w // 2:
                    dx -= map_w
                elif dx < -(map_w // 2):
                    dx += map_w
                if dy > map_h // 2:
                    dy -= map_h
                elif dy < -(map_h // 2):
                    dy += map_h
            return (
                (half + dx) * TILE_SIZE + TILE_SIZE // 2,
                (half + dy) * TILE_SIZE + TILE_SIZE // 2,
            )

        for fx in self.cannon_fx:
            duration = fx.get("duration", 0.35)
            timer = fx.get("timer", 0.0)
            progress = max(0.0, min(1.0, 1.0 - (timer / duration))) if duration > 0 else 1.0
            t_travel = min(1.0, progress / 0.7)
            sx, sy = _to_px(*fx["start_pos"])
            tx, ty = _to_px(*fx["target_pos"])
            cur_x = int(round(sx + (tx - sx) * t_travel))
            cur_y = int(round(sy + (ty - sy) * t_travel))

            if progress < 0.75:
                pygame.draw.circle(surface, (255, 96, 32), (cur_x, cur_y), 3)
                pygame.draw.circle(surface, (255, 255, 255), (cur_x, cur_y), 1)

            if progress >= 0.6:
                if fx.get("hit"):
                    if self.asset_mgr is not None:
                        fire_surf = self.asset_mgr.get_tile_surface("fire")
                        surface.blit(fire_surf, (tx - TILE_SIZE // 2, ty - TILE_SIZE // 2))
                    else:
                        pygame.draw.circle(surface, (255, 80, 20), (tx, ty), 6)
                        pygame.draw.circle(surface, (255, 220, 60), (tx, ty), 3)
                else:
                    pygame.draw.circle(surface, (120, 220, 255), (tx, ty), 5, 1)
                    pygame.draw.circle(surface, (255, 255, 255), (tx, ty), 3, 1)

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
                    # moongate model per refs (GBC funcs5.c:1134-1152; LW
                    # UltimaMisc.c:1511-1560; NES Bank0F MoonGateTbl:734-771):
                    # the kwarg is the SLOW phase — only site[trammel] renders.
                    moon_phase=self.trammel_phase,
                )
            self._render_cannon_fx(temp_v)
            scaled_v = pygame.transform.scale(temp_v, (v_size, v_size))
            surface.blit(scaled_v, (0, 0))
            self._render_sky_strip(surface, pane_right=v_size, pane_top=0)
            self._render_shrine_image(surface, v_size)

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
                    # Same SLOW-phase gate visibility contract as above.
                    moon_phase=self.trammel_phase,
                )
            self._render_cannon_fx(surface)
            self._render_sky_strip(surface, pane_right=176, pane_top=0)
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
