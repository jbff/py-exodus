"""Overworld exploration screen for Sosaria and Ambrosia."""
from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

import pygame

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
from py_exodus.screens.base import BaseScreen
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

        # Wandering overland creatures visible on Sosaria
        self.creatures: list[dict[str, Any]] = []
        if self.random_encounters_enabled:
            for _ in range(3):
                self._spawn_wandering_creature()

        map_name = getattr(self.game_map, "name", "Sosaria")
        self.text_log.add_message(f"Entering the realm of {map_name}...")
        self.text_log.add_message(f"Wind blows {self.party.wind_direction.name}.")

    def _load_world_map(self) -> None:
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
        self._play_overworld_music()

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

        # Directional Movement (Arrow keys, Keypad, or WASD)
        if event.key in (pygame.K_UP, pygame.K_KP8, pygame.K_w):
            self._move_avatar(Direction.NORTH)
        elif event.key in (pygame.K_DOWN, pygame.K_KP2):
            self._move_avatar(Direction.SOUTH)
        elif event.key in (pygame.K_LEFT, pygame.K_KP4):
            self._move_avatar(Direction.WEST)
        elif event.key in (pygame.K_RIGHT, pygame.K_KP6, pygame.K_d):
            self._move_avatar(Direction.EAST)
        elif event.key == pygame.K_SPACE:
            self._pass_turn()
        elif event.key == pygame.K_e:
            self._enter_portal()
        elif event.key == pygame.K_f and self.party.transport == Transport.SHIP:
            self._prompt_fire_cannons()
        elif event.key == pygame.K_b:
            self._toggle_board_transport()
        elif event.key == pygame.K_x:
            self._exit_transport()
        elif event.key in (pygame.K_q, pygame.K_s):
            self._save_game()
        elif event.key == pygame.K_z:
            self._toggle_zstats()
        elif event.key == pygame.K_c:
            self._prompt_cast()
        elif event.key == pygame.K_g:
            self._get_chest()
        elif event.key == pygame.K_i:
            self._ignite_torch()
        elif event.key == pygame.K_j:
            self._join_gold()
        elif event.key == pygame.K_p:
            self._peer_gem()
        elif event.key == pygame.K_a:
            self._prompt_attack_overworld()

    def _pass_turn(self) -> None:
        """Pass turn in place without moving avatar."""
        self.party.moves += 1
        self._check_food_consumption()
        self._update_creatures()
        self.text_log.add_message("Pass.")

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
            self.text_log.add_message(f"Ztats: {m.name} ({m.profession.name})")
        else:
            self.text_log.add_message("Ztats: Normal view")

    def _prompt_cast(self) -> None:
        """Prompt active member to cast an overland spell."""
        def _on_spell(code: str) -> None:
            c = code.strip().upper()[:1]
            if not c:
                return

            active = self.party.active_member
            if not active or active.mp < 5:
                self.text_log.add_message("Not enough MP to cast!")
                return

            # Map spell codes to effects
            if c in ("A", "H"):  # Heal spells
                active.mp = max(0, active.mp - 5)
                healed = 35
                for m in self.party.members:
                    if not m.is_dead():
                        m.hp = min(m.max_hp, m.hp + healed)
                if self.audio is not None:
                    self.audio.play_sfx("magic")
                self.text_log.add_message(f"Sanctu! Party wounds healed +{healed} HP.")
            elif c == "B":  # Light spell
                active.mp = max(0, active.mp - 5)
                self.party.torch_duration += 100
                if self.audio is not None:
                    self.audio.play_sfx("magic")
                self.text_log.add_message("Lorant! Mystical light radiates forth.")
            elif c in ("D", "M"):  # Teleport spells
                active.mp = max(0, active.mp - 15)
                import random
                self.party.x = (self.party.x + random.randint(-8, 8)) % (self.game_map.width if self.game_map else 64)
                self.party.y = (self.party.y + random.randint(-8, 8)) % (self.game_map.height if self.game_map else 64)
                if self.audio is not None:
                    self.audio.play_sfx("moongate_flash")
                self.text_log.add_message("Decul! Reality bends and shifts the party.")
            else:
                self.text_log.add_message("Cannot cast combat-only spell here!")

        self.text_log.prompt("Cast Spell? (A-P):", callback=_on_spell)

    def _get_chest(self) -> None:
        """Open chest on party's tile or adjacent tile."""
        target_obj = None
        target_idx = -1
        for idx, obj in enumerate(self.party.dynamic_objects):
            ox = obj.get("x", -1)
            oy = obj.get("y", -1)
            tile = obj.get("tile", "")
            if tile == "chest" and abs(ox - self.party.x) <= 1 and abs(oy - self.party.y) <= 1:
                target_obj = obj
                target_idx = idx
                break

        if target_obj is None or target_idx < 0:
            self.text_log.add_message("No chest here!")
            return

        self.party.dynamic_objects.pop(target_idx)
        import random
        # 20% trap chance
        trap_roll = random.random()
        if trap_roll < 0.10:
            self.text_log.add_message("TRAP! Acid burns party!")
            for m in self.party.members:
                m.hp = max(1, m.hp - 10)
        elif trap_roll < 0.20:
            self.text_log.add_message("TRAP! Poison gas released!")
            for m in self.party.members:
                m.status = Status.POISON

        gold_found = random.randint(50, 200)
        self.party.gold += gold_found
        if self.audio is not None:
            self.audio.play_sfx("trigger")
        self.text_log.add_message(f"Opened chest! Found {gold_found} gold pieces.")

    def _ignite_torch(self) -> None:
        """Light a torch from inventory."""
        if self.party.torches > 0:
            self.party.torches -= 1
            self.party.torch_duration += 100
            self.text_log.add_message("Torch ignited! Area is illuminated.")
        else:
            self.text_log.add_message("None owned!")

    def _join_gold(self) -> None:
        """Gather all party gold into primary pool."""
        self.party.pool_gold(0)
        self.text_log.add_message(f"All gold gathered into party pool: {self.party.gold} GP.")

    def _peer_gem(self) -> None:
        """Peer into mystical gem to survey surroundings."""
        if self.party.gems > 0:
            self.party.gems -= 1
            m_name = getattr(self.game_map, "name", "Sosaria")
            self.text_log.add_message(f"Gem vision: {m_name} at X={self.party.x}, Y={self.party.y}.")
        else:
            self.text_log.add_message("None owned!")

    def _exit_transport(self) -> None:
        """Dismount horse or ship onto foot."""
        if self.party.transport == Transport.FOOT:
            self.text_log.add_message("Already on foot.")
            return

        old_t = self.party.transport
        self.party.transport = Transport.FOOT
        if old_t == Transport.HORSE:
            self.text_log.add_message("Dismounted horse.")
        else:
            self.text_log.add_message("Disembarked ship.")

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

        self.text_log.prompt("Attack Direction? (N,S,E,W):", callback=_on_dir)

    def _move_avatar(self, direction: Direction) -> None:
        if self.game_map is None:
            return

        # Frigate sailing rules
        if self.party.transport == Transport.SHIP:
            # Check headwind
            if direction == self.party.wind_direction.reverse():
                self.text_log.add_message("Sailing against headwinds slows thee!")

        nx = (self.party.x + direction.dx) % self.game_map.width
        ny = (self.party.y + direction.dy) % self.game_map.height

        if can_move_to(self.game_map, nx, ny, transport=self.party.transport, party=self.party):
            self.party.x = nx
            self.party.y = ny
            self.party.moves += 1

            if self.audio is not None:
                self.audio.play_sfx("walk_normal")

            # Check food consumption
            if self.party.moves % 40 == 0:
                if self.party.food > 0:
                    self.party.food -= 1
                else:
                    self.text_log.add_message("Starving! Party loses health.")
                    for m in self.party.members:
                        m.character.hp = max(0, m.character.hp - 2)

            # Check moongate teleports
            self._check_moongates()

            # Check random encounters
            if self.random_encounters_enabled:
                self._check_random_encounter()
        else:
            if self.audio is not None:
                self.audio.play_sfx("blocked")

    def _prompt_fire_cannons(self) -> None:
        """Fire frigate broadside cannons in a given direction."""
        def _on_dir(d_str: str) -> None:
            d = Direction.from_name_or_key(d_str)
            if d is None:
                self.text_log.add_message("Invalid firing direction!")
                return
            self._fire_cannons(d)

        self.text_log.prompt("Fire cannon direction? (N,S,E,W):", callback=_on_dir)

    def _fire_cannons(self, direction: Direction) -> None:
        if self.audio is not None:
            self.audio.play_sfx("cannon") or self.audio.play_sfx("enemy_magic_proj")

        self.text_log.add_message(f"BOOM! Broadside fired {direction.name}!")

        # Trace cannonball up to 3 tiles
        if self.game_map is None:
            return
        cx, cy = self.party.x, self.party.y
        for step in range(1, 4):
            tx = (cx + direction.dx * step) % self.game_map.width
            ty = (cy + direction.dy * step) % self.game_map.height
            tile = self.game_map.get_tile(tx, ty)
            if tile is not None and not tile.walkable and not tile.sailable:
                self.text_log.add_message("Cannonball crashed into the shoreline!")
                break

    def _enter_portal(self) -> None:
        """Enter city, dungeon, shrine, or whirlpool portal at party location."""
        if self.game_map is None:
            return

        portal = None
        for p in self.game_map.portals:
            if p.x == self.party.x and p.y == self.party.y:
                portal = p
                break

        if portal is None:
            self.text_log.add_message("Nothing to enter here!")
            return

        dest_id = portal.dest_map_id
        start_x = portal.start_x
        start_y = portal.start_y

        # Determine if destination is town, dungeon, or shrine
        if dest_id in (55, 56, 57, 58):  # Shrine
            from py_exodus.screens.shrine import ShrineScreen

            stat_names = {
                55: "wisdom",
                56: "dexterity",
                57: "intelligence",
                58: "strength",
            }
            shrine = ShrineScreen(
                party=self.party,
                stat_name=stat_names.get(dest_id, "strength"),
                asset_mgr=self.asset_mgr,
                return_screen=self,
                manager=self.manager,
            )
            if self.manager is not None:
                self.manager.push_screen(shrine)
            else:
                self.next_screen = shrine
                self.is_finished = True

        elif dest_id in (14, 15, 16, 17, 18, 19, 20):  # Dungeons
            from py_exodus.screens.dungeon_screen import DungeonScreen

            dungeon = DungeonScreen(
                party=self.party,
                map_id=dest_id,
                asset_mgr=self.asset_mgr,
                audio=self.audio,
                return_screen=self,
                manager=self.manager,
            )
            if self.manager is not None:
                self.manager.push_screen(dungeon)
            else:
                self.next_screen = dungeon
                self.is_finished = True

        else:  # Cities / Towns / Castles
            from py_exodus.screens.town import TownScreen

            town = TownScreen(
                party=self.party,
                map_id=dest_id,
                start_x=start_x,
                start_y=start_y,
                asset_mgr=self.asset_mgr,
                audio=self.audio,
                return_screen=self,
                manager=self.manager,
            )
            if self.manager is not None:
                self.manager.push_screen(town)
            else:
                self.next_screen = town
                self.is_finished = True

    def _toggle_board_transport(self) -> None:
        """Board or dismount horse/frigate."""
        if self.party.transport == Transport.FOOT:
            # Check adjacent tiles or party location for transport
            self.party.transport = Transport.HORSE
            self.text_log.add_message("Mounted horse! Movement speed increased.")
        elif self.party.transport == Transport.HORSE:
            self.party.transport = Transport.FOOT
            self.text_log.add_message("Dismounted to foot.")
        elif self.party.transport == Transport.SHIP:
            self.party.transport = Transport.FOOT
            self.text_log.add_message("Disembarked ship to foot.")

    def _check_moongates(self) -> None:
        """Check if party stepped onto an active moongate."""
        if self.game_map is None:
            return
        for gate in self.game_map.moongates:
            if gate.phase == (self.moon_phase % 8):
                if gate.x == self.party.x and gate.y == self.party.y:
                    # Teleport to destination gate
                    dest_gate = self.game_map.moongates[(gate.d1) % len(self.game_map.moongates)]
                    self.party.x = dest_gate.x
                    self.party.y = dest_gate.y
                    self.text_log.add_message("Stepped through mystical moongate!")
                    if self.audio is not None:
                        self.audio.play_sfx("moongate_flash")
                    break

    def _check_food_consumption(self) -> None:
        if self.party.moves % 40 == 0:
            if self.party.food > 0:
                self.party.food -= 1
            else:
                self.text_log.add_message("Starving! Party loses health.")
                for m in self.party.members:
                    m.character.hp = max(0, m.character.hp - 2)

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
        """Move wandering creatures towards the party or wander."""
        if not self.creatures and self.random_encounters_enabled:
            self._spawn_wandering_creature()

        import random
        if random.random() < 0.25 and len(self.creatures) < 6:
            self._spawn_wandering_creature()

        width = self.game_map.width if self.game_map else 64
        height = self.game_map.height if self.game_map else 64

        survivors: list[dict[str, Any]] = []
        for c in self.creatures:
            cx, cy = c["x"], c["y"]
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
                self._trigger_combat(c.get("tile_name", "orc"))
                return

            survivors.append(c)

        self.creatures = survivors

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
        """Save party progress to JSON file."""
        try:
            from py_exodus.save_system import SaveSystem

            SaveSystem.save_game(self.party, "saves/party.json")
            self.text_log.add_message("Game saved successfully.")
        except Exception as e:
            self.text_log.add_message("Save failed!")

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
