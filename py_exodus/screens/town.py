"""City and castle exploration screen with NPC and vendor interactions."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pygame

from py_exodus.constants import (
    Direction,
    Status,
    TileAttrib,
    Transport,
)
from py_exodus.screens.base import BaseScreen
from py_exodus.ui.renderer import WorldRenderer, can_move_to
from py_exodus.ui.stats_panel import StatsPanel
from py_exodus.ui.text_log import (
    EGA_BLACK,
    TextLog,
)

if TYPE_CHECKING:
    from py_exodus.assets import AssetManager
    from py_exodus.audio import AudioManager
    from py_exodus.entities.defs import VendorDef
    from py_exodus.entities.party import Party
    from py_exodus.world.map import GameMap, MapNpc


class TownScreen(BaseScreen):
    """Town and castle navigation screen supporting NPC dialogues and vendor shopping."""

    def __init__(
        self,
        party: Party,
        map_id: int | str = 1,
        asset_mgr: AssetManager | None = None,
        audio: AudioManager | None = None,
        return_screen: BaseScreen | None = None,
        start_x: int | None = None,
        start_y: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(return_screen=return_screen, **kwargs)
        self.party = party
        self.map_id = map_id
        self.asset_mgr = asset_mgr
        self.audio = audio

        self.game_map: GameMap | None = None
        self._load_town_map()

        # Coordinates
        self.avatar_x = start_x if start_x is not None else 32
        self.avatar_y = start_y if start_y is not None else 60
        self.anim_frame = 0
        self.anim_timer = 0.0

        self.world_renderer = (
            WorldRenderer(asset_mgr) if asset_mgr is not None else None
        )
        self.stats_panel = StatsPanel()
        self.text_log = TextLog(max_lines=5, wrap_width=28)

        town_name = getattr(self.game_map, "name", str(map_id)).title()
        self.text_log.add_message(f"Entering {town_name}...")
        self.text_log.add_message("Guards and citizens walk the streets.")

    def _load_town_map(self) -> None:
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

    def on_enter(self) -> None:
        super().on_enter()
        self._play_town_music()

    def _play_town_music(self) -> None:
        if self.audio is None:
            return
        m_id = str(self.map_id).lower()
        if m_id in ("1", "british", "castle"):
            self.audio.play_music("fanfare")
        elif m_id in ("2", "7", "10", "exodus", "devil", "death"):
            self.audio.play_music("exodus")
        else:
            self.audio.play_music("towns")

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return

        if self.text_log.is_waiting_for_input:
            self.text_log.handle_event(event)
            return

        # Movement
        if event.key in (pygame.K_UP, pygame.K_w):
            self._try_move(Direction.NORTH)
        elif event.key in (pygame.K_DOWN, pygame.K_s):
            self._try_move(Direction.SOUTH)
        elif event.key in (pygame.K_LEFT, pygame.K_a):
            self._try_move(Direction.WEST)
        elif event.key in (pygame.K_RIGHT, pygame.K_d):
            self._try_move(Direction.EAST)
        elif event.key == pygame.K_t:
            self._prompt_talk()
        elif event.key in (pygame.K_o, pygame.K_l):
            self._prompt_door(open_door=True)
        elif event.key == pygame.K_u:
            self._prompt_door(open_door=False)
        elif event.key == pygame.K_x:
            self._exit_town()

    def _try_move(self, direction: Direction) -> None:
        if self.game_map is None:
            return

        nx = self.avatar_x + direction.dx
        ny = self.avatar_y + direction.dy

        # Check exit border
        if not (0 <= nx < self.game_map.width and 0 <= ny < self.game_map.height):
            self._exit_town()
            return

        if can_move_to(self.game_map, nx, ny, transport=Transport.FOOT, party=self.party):
            self.avatar_x = nx
            self.avatar_y = ny
            if self.audio is not None:
                self.audio.play_sfx("walk_normal")
        else:
            if self.audio is not None:
                self.audio.play_sfx("blocked")

    def _exit_town(self) -> None:
        self.text_log.add_message("Leaving city...")
        if self.party.map_id == 1 or str(self.map_id) in ("1", "british", "castle"):
            self.party.map_id = 0
            self.party.x = 45
            self.party.y = 18
        self.exit_screen()

    def _prompt_talk(self) -> None:
        def _on_dir(d_str: str) -> None:
            d = Direction.from_name_or_key(d_str)
            if d is None:
                self.text_log.add_message("Invalid direction!")
                return
            self._talk_to_direction(d)

        self.text_log.prompt("Talk direction? (N,S,E,W):", callback=_on_dir)

    def _talk_to_direction(self, direction: Direction) -> None:
        if self.game_map is None:
            return

        tx = self.avatar_x + direction.dx
        ty = self.avatar_y + direction.dy

        npc = self._find_npc_at(tx, ty)
        if npc is None:
            self.text_log.add_message("Funny, no response!")
            return

        tile_name = getattr(npc, "tile", "").lower()
        npc_name = getattr(npc, "name", "").lower()

        # Check Lord British
        if "british" in tile_name or "british" in npc_name or npc_name == "lord british":
            self._interact_lord_british()
            return

        # Check Vendor
        vendor = self._find_vendor_at(npc)
        if vendor is not None:
            self._start_vendor_shopping(vendor)
            return

        # Standard dialogue
        conv = getattr(npc, "conversation", None)
        if conv:
            self.text_log.add_message(f'"{conv}"')
        else:
            self.text_log.add_message("Funny, no response!")

    def _find_npc_at(self, x: int, y: int) -> MapNpc | None:
        if self.game_map is None:
            return None
        for npc in self.game_map.npcs:
            if npc.x == x and npc.y == y:
                return npc
        return None

    def _find_vendor_at(self, npc: MapNpc) -> VendorDef | None:
        if self.asset_mgr is None:
            return None
        v = self.asset_mgr.get_vendor(self.map_id, npc.x, npc.y)
        if v is None and hasattr(npc, "name"):
            # Check by name
            v = self.asset_mgr.vendors.get(npc.name.lower())
        return v

    def _interact_lord_british(self) -> None:
        """Handle Lord British character level advancements and resurrection."""
        revived_any = False
        for pm in self.party.members:
            if pm.status in (Status.DEAD, Status.ASHES):
                pm.status = Status.GOOD
                pm.hp = pm.max_hp
                revived_any = True

        if revived_any:
            self.text_log.add_message("Lord British says: 'Thou art resurrected!'")
            if self.audio is not None:
                self.audio.play_sfx("magic")

        advanced_any = False
        for member in self.party.members:
            char = member.character
            if char.meet_lord_british():
                advanced_any = True

        if advanced_any:
            self.text_log.add_message("Lord British says:\n'Thou hast been advanced!'")
            if self.audio is not None:
                self.audio.play_sfx("magic")
        elif not revived_any:
            self.text_log.add_message("Lord British says:\n'Welcome my child..\nExperience more!'")

    def _start_vendor_shopping(self, vendor: VendorDef) -> None:
        """Interactive shopping dialog stream with vendor via TextLog."""
        if self.audio is not None:
            self.audio.play_music("shopping")

        self.text_log.add_message(f"Welcome to {vendor.name}!")
        self.text_log.add_message(f"Owner: {vendor.owner}")

        # Show catalog
        if vendor.items:
            for item in vendor.items[:6]:
                self.text_log.add_message(f"{item.choice}) {item.name} - {item.price}gp")

        def _on_choice(choice: str) -> None:
            c = choice.strip().lower()
            if not c or c == "bye":
                self.text_log.add_message("Good journey to thee!")
                self._play_town_music()
                return

            item = vendor.get_item(c)
            if item is None:
                self.text_log.add_message("We have no such ware.")
                self._play_town_music()
                return

            if self.party.gold < item.price:
                self.text_log.add_message("Thou cannot afford that!")
            else:
                self.party.gold -= item.price
                active = self.party.active_member
                if active is not None and item.weapon_type:
                    active.character.weapon = item.weapon_type
                elif active is not None and item.armor_type:
                    active.character.armor = item.armor_type
                self.text_log.add_message(f"Bought {item.name}! A fine bargain.")
                if self.audio is not None:
                    self.audio.play_sfx("trigger")

            self._play_town_music()

        self.text_log.prompt("What wouldst thou buy? (Choice):", callback=_on_choice)

    def _prompt_door(self, open_door: bool) -> None:
        def _on_dir(d_str: str) -> None:
            d = Direction.from_name_or_key(d_str)
            if d is None:
                self.text_log.add_message("Invalid direction!")
                return
            self._handle_door(d, open_door)

        action_name = "Open" if open_door else "Unlock"
        self.text_log.prompt(f"{action_name} door direction? (N,S,E,W):", callback=_on_dir)

    def _handle_door(self, direction: Direction, open_door: bool) -> None:
        if self.game_map is None:
            return
        tx = self.avatar_x + direction.dx
        ty = self.avatar_y + direction.dy
        tile = self.game_map.get_tile(tx, ty)
        if tile is None:
            self.text_log.add_message("Nothing there!")
            return

        attribs = getattr(tile, "attribs", TileAttrib.NONE)
        if bool(attribs & (TileAttrib.DOOR | TileAttrib.LOCKEDDOOR)):
            # Replace door tile with floor/unblocked
            replacement = getattr(self.game_map, "default_floor", tile)
            self.game_map.set_tile(tx, ty, replacement)
            self.text_log.add_message("Door opened!")
            if self.audio is not None:
                self.audio.play_sfx("trigger")
        else:
            self.text_log.add_message("No door there!")

    def update(self, dt: float) -> None:
        self.anim_timer += dt
        if self.anim_timer >= 0.2:
            self.anim_timer = 0.0
            self.anim_frame = (self.anim_frame + 1) % 4

    def render(self, surface: pygame.Surface) -> None:
        surface.fill(EGA_BLACK)

        # 1. 11x11 Town Viewport (176x176 at 0, 0)
        if self.world_renderer is not None and self.game_map is not None:
            self.world_renderer.render_viewport(
                surface,
                self.game_map,
                center_x=self.avatar_x,
                center_y=self.avatar_y,
                anim_frame=self.anim_frame,
                party=self.party,
                dest_pos=(0, 0),
            )

        # 2. Right Sidebar (Party Stats)
        self.stats_panel.render(
            surface,
            self.party,
            rect=pygame.Rect(176, 0, surface.get_width() - 176, surface.get_height()),
        )

        # 3. Bottom HUD Text Log
        log_h = max(24, surface.get_height() - 176)
        self.text_log.render(
            surface,
            rect=pygame.Rect(0, 176, 176, log_h),
            draw_border=True,
        )
