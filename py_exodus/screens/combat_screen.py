"""Tactical grid CombatScreen wrapping CombatArena for 11x11 battles."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pygame

from py_exodus.combat.arena import Action, ActionType, CombatArena
from py_exodus.combat.magic import (
    DIRECTIONAL_SPELLS,
    TARGETED_MEMBER_SPELLS,
    get_castable_spell_types,
    resolve_spell,
)
from py_exodus.constants import (
    COMBAT_HEIGHT,
    COMBAT_WIDTH,
    TILE_SIZE,
    ArmorType,
    Direction,
    Spell,
    WeaponType,
)
from py_exodus.entities.party import PartyMember
from py_exodus.screens.base import BaseScreen
from py_exodus.ui.renderer import WorldRenderer
from py_exodus.ui.stats_panel import StatsPanel
from py_exodus.ui.text_log import (
    EGA_BLACK,
    EGA_BRIGHT_CYAN,
    EGA_BRIGHT_GREEN,
    EGA_BRIGHT_RED,
    EGA_DARK_GRAY,
    EGA_WHITE,
    EGA_YELLOW,
    TextLog,
    get_hud_font,
)

if TYPE_CHECKING:
    from py_exodus.assets import AssetManager
    from py_exodus.audio import AudioManager
    from py_exodus.entities.party import Party
    from py_exodus.world.map import ConflictMap


class CombatScreen(BaseScreen):
    """Interactive screen for 11x11 tactical turn-based combat encounters."""

    def __init__(
        self,
        party: Party,
        combat_map: ConflictMap,
        creature_tile: str = "orc",
        asset_mgr: AssetManager | None = None,
        audio: AudioManager | None = None,
        return_screen: BaseScreen | None = None,
        monster_count: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(return_screen=return_screen, **kwargs)
        self.party = party
        self.combat_map = combat_map
        self.creature_tile = creature_tile
        self.asset_mgr = asset_mgr
        self.audio = audio

        self.arena = CombatArena(
            party=party,
            combat_map=combat_map,
            creature_tile=creature_tile,
            asset_mgr=asset_mgr,
            monster_count=monster_count,
        )

        self.world_renderer = (
            WorldRenderer(asset_mgr) if asset_mgr is not None else None
        )
        self.stats_panel = StatsPanel()
        self.text_log = TextLog(max_lines=5, wrap_width=28)

        # Seed initial combat message
        c_name = self.arena.creature_def.name
        self.text_log.add_message(f"Ambushed by {c_name}s!")
        for msg in self.arena.log_messages:
            self.text_log.add_message(msg)
        self.arena.log_messages.clear()

        self._pending_action_type: ActionType | None = None
        self.awaiting_exit_ack = False
        self.flash_timer: float = 0.0
        self.combat_fx: list[dict[str, Any]] = []
        self.dying_monsters: list[dict[str, Any]] = []

    @property
    def active_party_member(self) -> PartyMember | None:
        """Return currently active party member taking turn in combat."""
        return self.party.get_member(self.arena.active_party_member_idx)

    def on_enter(self) -> None:
        super().on_enter()
        if self.audio is not None:
            self.audio.play_music("combat")

    def on_exit(self) -> None:
        super().on_exit()
        if self.audio is not None:
            self.audio.stop_music()

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return

        # If waiting for prompt input (e.g. Direction or Spell code)
        if self.text_log.is_waiting_for_input:
            self.text_log.handle_event(event)
            return

        # If combat is finished, any key acknowledges and exits
        if self.arena.is_finished:
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE, pygame.K_ESCAPE):
                if self.arena.is_defeat:
                    self._handle_defeat_exit()
                else:
                    self.exit_screen()
            return

        # Standard combat keys
        active_member = self.active_party_member
        if active_member is None:
            return

        # Movement keys (Arrow keys and Keypad)
        if event.key in (pygame.K_UP, pygame.K_KP8):
            self._execute_action(Action.move(Direction.NORTH))
        elif event.key in (pygame.K_DOWN, pygame.K_KP2):
            self._execute_action(Action.move(Direction.SOUTH))
        elif event.key in (pygame.K_LEFT, pygame.K_KP4):
            self._execute_action(Action.move(Direction.WEST))
        elif event.key in (pygame.K_RIGHT, pygame.K_KP6):
            self._execute_action(Action.move(Direction.EAST))
        elif event.key in (pygame.K_SPACE, pygame.K_p):
            self._execute_action(Action.pass_turn())
        elif event.key == pygame.K_f:
            self._execute_action(Action(ActionType.FLEE, direction=Direction.SOUTH))
        elif event.key == pygame.K_a:  # Attack command
            self._prompt_attack()
        elif event.key == pygame.K_c:  # Cast command
            self._prompt_cast()
        elif event.key == pygame.K_r:  # Ready weapon
            self._prompt_ready_weapon()
        elif event.key == pygame.K_w:  # Wear armor
            self._prompt_wear_armor()

    def _prompt_attack(self) -> None:
        """Prompt active member for attack direction."""
        active = self.active_party_member
        if not active:
            return

        def _on_dir(d_str: str) -> None:
            d = Direction.from_name_or_key(d_str)
            if d is None:
                self.text_log.add_message("Invalid direction!")
                return
            self._execute_action(Action.attack(d))

        self.text_log.prompt("Direction? (N,S,E,W):", callback=_on_dir, single_char=True)

    def _prompt_cast(self) -> None:
        """Prompt active member for spell casting."""
        active = self.active_party_member
        if not active:
            return

        char = active.character
        types = get_castable_spell_types(char.profession)
        if not types:
            prof_name = char.profession.value.capitalize() if hasattr(char.profession, "value") else str(char.profession)
            self.text_log.add_message(f"{char.name} ({prof_name}) cannot cast spells!")
            return

        def _ask_spell_code(discipline: str) -> None:
            type_label = "Wizard" if discipline == "wizard" else "Cleric"

            def _on_spell(code: str) -> None:
                code_upper = code.strip().upper()
                found_spell = resolve_spell(code_upper, spell_type=discipline, caster=active)
                if found_spell is None:
                    self.text_log.add_message("Unknown spell!")
                    return

                if not found_spell.can_cast(char.profession):
                    self.text_log.add_message(f"{char.name} cannot cast {found_spell.name}!")
                    return

                if char.mp < found_spell.mp_cost:
                    self.text_log.add_message(f"Not enough MP! Need {found_spell.mp_cost} MP.")
                    return

                if found_spell in DIRECTIONAL_SPELLS:
                    def _on_dir(d_str: str) -> None:
                        d = Direction.from_name_or_key(d_str)
                        if d is None:
                            self.text_log.add_message("Invalid direction!")
                            return
                        self._execute_action(Action.cast(found_spell, direction=d))

                    self.text_log.prompt("Direction? (N,S,E,W):", callback=_on_dir, single_char=True)
                elif found_spell in TARGETED_MEMBER_SPELLS:
                    def _on_target(target_str: str) -> None:
                        try:
                            t_idx = int(target_str.strip()) - 1
                            target_m = self.party.get_member(t_idx)
                        except ValueError:
                            target_m = None
                        if target_m is None:
                            self.text_log.add_message("Invalid member #!")
                            return
                        self._execute_action(Action.cast(found_spell, target_member=target_m))

                    self.text_log.prompt("On who? (1-4):", callback=_on_target, single_char=True)
                else:
                    self._execute_action(Action.cast(found_spell))

            self.text_log.prompt(f"{type_label} Spell? (A-P):", callback=_on_spell, single_char=True)

        if len(types) > 1:
            def _on_type(t_str: str) -> None:
                t = t_str.strip().upper()
                if t in ("W", "WIZARD"):
                    _ask_spell_code("wizard")
                elif t in ("C", "CLERIC"):
                    _ask_spell_code("cleric")
                else:
                    self.text_log.add_message("Invalid choice! Enter W or C.")

            self.text_log.prompt("Spell Type? [W]izard or [C]leric:", callback=_on_type, single_char=True)
        else:
            _ask_spell_code(types[0])

    def _prompt_ready_weapon(self) -> None:
        """Prompt active member to ready a weapon (A-P)."""
        active = self.active_party_member
        if not active:
            return

        weapon_types = list(WeaponType)
        self.text_log.add_message(f"-- Ready Weapon for {active.name} --")
        for w_idx, wt in enumerate(weapon_types):
            letter = chr(ord('A') + w_idx)
            if wt == WeaponType.NONE:
                self.text_log.add_message(f"{letter} - Hands")
                continue
            cnt = active.weapons.get(wt, 0)
            is_equipped = (active.weapon == wt)
            if cnt > 0 or is_equipped:
                status_tag = " (readied)" if is_equipped else f" ({cnt})"
                self.text_log.add_message(f"{letter} - {wt.name.capitalize()}{status_tag}")

        def _on_weap(w_code: str) -> None:
            c = w_code.strip().upper()
            if not c:
                return
            w_idx = ord(c[0]) - ord('A')
            if 0 <= w_idx < len(weapon_types):
                success = active.ready_weapon(w_idx, self.asset_mgr)
                if success:
                    self.text_log.add_message(f"Success! {active.name} readied {active.weapon.name}.")
                    self._execute_action(Action.pass_turn())
                else:
                    self.text_log.add_message("Cannot ready that weapon!")
            else:
                self.text_log.add_message("Invalid weapon selection!")

        self.text_log.prompt("Ready Weapon? (A-P): ", callback=_on_weap, single_char=True)

    def _prompt_wear_armor(self) -> None:
        """Prompt active member to wear armor (A-H)."""
        active = self.active_party_member
        if not active:
            return

        armor_types = list(ArmorType)
        self.text_log.add_message(f"-- Wear Armor for {active.name} --")
        for a_idx, at in enumerate(armor_types):
            letter = chr(ord('A') + a_idx)
            if at == ArmorType.NONE:
                self.text_log.add_message(f"{letter} - Skin")
                continue
            cnt = active.armors.get(at, 0)
            is_equipped = (active.armor == at)
            if cnt > 0 or is_equipped:
                status_tag = " (worn)" if is_equipped else f" ({cnt})"
                self.text_log.add_message(f"{letter} - {at.name.capitalize()}{status_tag}")

        def _on_arm(a_code: str) -> None:
            c = a_code.strip().upper()
            if not c:
                return
            a_idx = ord(c[0]) - ord('A')
            if 0 <= a_idx < len(armor_types):
                success = active.wear_armor(a_idx, self.asset_mgr)
                if success:
                    self.text_log.add_message(f"Success! {active.name} wears {active.armor.name}.")
                    self._execute_action(Action.pass_turn())
                else:
                    self.text_log.add_message("Cannot wear that armor!")
            else:
                self.text_log.add_message("Invalid armor selection!")

        self.text_log.prompt("Wear Armor? (A-H): ", callback=_on_arm, single_char=True)

    def _execute_action(self, action: Action) -> None:
        """Execute action in CombatArena, trigger visual FX, update audio, and sync logs."""
        active_before = self.active_party_member
        p_idx = self.arena.active_party_member_idx
        start_pos = self.arena.player_positions.get(p_idx, (5, 5))

        # Snapshot living monsters to keep dying monsters visible during hit animations
        monsters_before = [
            {"tile": m.tile, "name": m.name, "x": m.x, "y": m.y, "obj": m}
            for m in self.arena.monsters if not m.is_dead
        ]

        res = self.arena.execute_turn(action)

        current_living_objs = {m for m in self.arena.monsters if not m.is_dead}
        for mb in monsters_before:
            if mb["obj"] not in current_living_objs:
                self.dying_monsters.append({
                    "tile": mb["tile"],
                    "name": mb["name"],
                    "x": mb["x"],
                    "y": mb["y"],
                    "timer": 0.35,
                })

        # Reverse viewport screen flash on cast
        if action.type == ActionType.CAST:
            self.flash_timer = 0.10

        # Visual FX for weapon attack
        if action.type == ActionType.ATTACK and res.attack_res:
            ares = res.attack_res
            w_def = None
            if self.asset_mgr and active_before and hasattr(active_before, "weapon"):
                w_name = active_before.weapon.value if hasattr(active_before.weapon, "value") else str(active_before.weapon)
                w_def = self.asset_mgr.get_weapon(w_name)

            is_magic = w_def is not None and (w_def.magic or getattr(w_def, "hit_tile", "") == "magic")
            color = (85, 255, 255) if is_magic else (255, 85, 85)
            hit_tile = "magic" if is_magic else "fire"

            target_pos = ares.target_pos
            if not target_pos and ares.projectile_path:
                target_pos = ares.projectile_path[-1]

            path = ares.projectile_path if ares.projectile_path else ([target_pos] if target_pos else [])
            self.combat_fx.append({
                "type": "weapon",
                "color": color,
                "start_pos": start_pos,
                "path": path,
                "target_pos": target_pos,
                "hit_tile": hit_tile if ares.hit else None,
                "duration": 0.35,
                "timer": 0.35,
            })
        elif action.type == ActionType.CAST:
            spell_obj = action.spell
            s_name = getattr(spell_obj, "name", str(spell_obj)).upper()
            if "FULGAR" in s_name:
                color = (255, 60, 60)
            elif "DECORP" in s_name:
                color = (200, 60, 255)
            else:
                color = (0, 180, 255)

            target_pos = None
            path = []
            hit = False
            if res.spell_res is not None:
                path = res.spell_res.projectile_path
                target_pos = res.spell_res.target_pos
                hit = res.spell_res.hit

            if not path and action.direction:
                d = action.direction
                for step in range(1, 6):
                    step_x = start_pos[0] + d.dx * step
                    step_y = start_pos[1] + d.dy * step
                    if 0 <= step_x < COMBAT_WIDTH and 0 <= step_y < COMBAT_HEIGHT:
                        path.append((step_x, step_y))
                        target_pos = (step_x, step_y)

            if not target_pos and path:
                target_pos = path[-1]

            if path or target_pos:
                self.combat_fx.append({
                    "type": "spell",
                    "color": color,
                    "start_pos": start_pos,
                    "path": path,
                    "target_pos": target_pos,
                    "hit_tile": "magic" if hit else None,
                    "duration": 0.35,
                    "timer": 0.35,
                })

        # Sync arena log messages to HUD
        for msg in self.arena.log_messages:
            self.text_log.add_message(msg)
        self.arena.log_messages.clear()

        # Play audio effects
        if self.audio is not None:
            if action.type == ActionType.ATTACK:
                self.audio.play_sfx("pc_attack")
            elif action.type == ActionType.CAST:
                self.audio.play_sfx("magic")
            elif action.type == ActionType.MOVE:
                self.audio.play_sfx("walk_normal")

        # Check end states
        if self.arena.is_finished:
            if self.arena.is_victory:
                self.text_log.add_message("VICTORY! All foes slain.")
                self.text_log.add_message("Press Enter to continue.")
                if self.audio is not None:
                    self.audio.play_sfx("Fanfare")
            elif self.arena.is_defeat:
                self.text_log.add_message("DEFEAT! Thy party has fallen.")
                self.text_log.add_message("Press Enter to continue.")
            elif self.arena.is_fled:
                self.text_log.add_message("Escaped from combat!")
                self.exit_screen()

    def _handle_defeat_exit(self) -> None:
        """Handle wipeout defeat: warp party to Castle British, revive, and transition to TownScreen."""
        self.party.map_id = 1
        self.party.x = 32
        self.party.y = 61
        self.party.revive_all()

        from py_exodus.screens.overworld import OverworldScreen
        from py_exodus.screens.town import TownScreen

        ow_screen = self.return_screen
        if isinstance(ow_screen, TownScreen) and isinstance(ow_screen.return_screen, OverworldScreen):
            ow_screen = ow_screen.return_screen

        if not isinstance(ow_screen, OverworldScreen):
            ow_screen = OverworldScreen(
                party=self.party,
                map_id=0,
                asset_mgr=self.asset_mgr,
                audio=self.audio,
                start_x=44,
                start_y=20,
                manager=self.manager,
            )

        castle_screen = TownScreen(
            party=self.party,
            map_id=1,
            asset_mgr=self.asset_mgr,
            audio=self.audio,
            return_screen=ow_screen,
            start_x=32,
            start_y=61,
            manager=self.manager,
        )

        self.is_finished = True
        self.is_active = False
        self.next_screen = castle_screen
        if self.manager is not None:
            self.manager.set_screen(castle_screen)

    def update(self, dt: float) -> None:
        self.flash_timer = max(0.0, self.flash_timer - dt)
        for fx in list(self.combat_fx):
            fx["timer"] -= dt
            if fx["timer"] <= 0:
                self.combat_fx.remove(fx)
        for dm in list(self.dying_monsters):
            dm["timer"] -= dt
            if dm["timer"] <= 0:
                self.dying_monsters.remove(dm)

    def render(self, surface: pygame.Surface) -> None:
        surface.fill(EGA_BLACK)
        w, h = surface.get_width(), surface.get_height()
        scale = 3 if w >= 640 else 1
        v_size = 176 * scale

        # Render 11x11 viewport into standard 176x176 buffer
        temp_v = pygame.Surface((176, 176))
        if self.world_renderer is not None:
            self.world_renderer.render_viewport(
                temp_v,
                self.arena.combat_map,
                center_x=5,
                center_y=5,
                dest_pos=(0, 0),
            )
        else:
            self._render_grid_fallback(temp_v)

        self._render_monsters(temp_v)
        self._render_players(temp_v)
        self._apply_flash_invert(temp_v)
        self._render_combat_fx(temp_v)

        if scale > 1:
            scaled_v = pygame.transform.scale(temp_v, (v_size, v_size))
            surface.blit(scaled_v, (0, 0))

            # Right Sidebar (Party Stats) at native high resolution
            self.stats_panel.render(
                surface,
                self.party,
                inspect_index=self.arena.active_party_member_idx,
                rect=pygame.Rect(v_size, 0, w - v_size, h),
            )

            # Bottom HUD Text Log at native resolution
            self.text_log.render(
                surface,
                rect=pygame.Rect(0, v_size, v_size, h - v_size),
                draw_border=True,
            )
        else:
            surface.blit(temp_v, (0, 0))

            self.stats_panel.render(
                surface,
                self.party,
                inspect_index=self.arena.active_party_member_idx,
                rect=pygame.Rect(176, 0, w - 176, h),
            )

            log_h = max(24, h - 176)
            self.text_log.render(
                surface,
                rect=pygame.Rect(0, 176, 176, log_h),
                draw_border=True,
            )

    def _render_combat_fx(self, surface: pygame.Surface) -> None:
        """Render active weapon/spell projectile travelling orbs and hit/fire bursts."""
        for fx in self.combat_fx:
            color = fx.get("color", (255, 85, 85))
            duration = fx.get("duration", 0.35)
            timer = fx.get("timer", 0.35)
            start_pos = fx.get("start_pos")
            target_pos = fx.get("target_pos")
            hit_tile = fx.get("hit_tile")

            progress = 1.0 - (timer / duration) if duration > 0 else 1.0

            # Draw projectile travelling from start_pos to target_pos
            if start_pos and target_pos:
                t_travel = min(1.0, progress / 0.7)
                curr_x = start_pos[0] + (target_pos[0] - start_pos[0]) * t_travel
                curr_y = start_pos[1] + (target_pos[1] - start_pos[1]) * t_travel
                px = int(curr_x * TILE_SIZE + TILE_SIZE // 2)
                py = int(curr_y * TILE_SIZE + TILE_SIZE // 2)

                # Outer glowing orb (radius 4, 8px diameter)
                pygame.draw.circle(surface, color, (px, py), 4)
                # Inner bright white core (radius 2)
                pygame.draw.circle(surface, (255, 255, 255), (px, py), 2)
            else:
                path = fx.get("path", [])
                for pt in path:
                    px = pt[0] * TILE_SIZE + TILE_SIZE // 2
                    py = pt[1] * TILE_SIZE + TILE_SIZE // 2
                    pygame.draw.circle(surface, color, (px, py), 4)
                    pygame.draw.circle(surface, (255, 255, 255), (px, py), 2)

            # Hit burst on target once projectile arrives
            if progress >= 0.5 and target_pos and hit_tile and self.asset_mgr is not None:
                try:
                    hit_surf = self.asset_mgr.get_tile_surface(hit_tile)
                    if hit_surf is not None:
                        surface.blit(hit_surf, (target_pos[0] * TILE_SIZE, target_pos[1] * TILE_SIZE))
                except Exception:
                    pass

    def _apply_flash_invert(self, surface: pygame.Surface) -> None:
        """Invert viewport colors for classic spellcasting screen flash."""
        if self.flash_timer > 0:
            inv = pygame.Surface(surface.get_size())
            inv.fill((255, 255, 255))
            inv.blit(surface, (0, 0), special_flags=pygame.BLEND_SUB)
            surface.blit(inv, (0, 0))

    def _render_monsters(self, surface: pygame.Surface) -> None:
        font = get_hud_font(size=12)
        for m in self.arena.monsters:
            if m.is_dead:
                continue
            px = m.x * TILE_SIZE
            py = m.y * TILE_SIZE
            # Attempt tile blit if asset_mgr available
            blitted = False
            if self.asset_mgr is not None:
                try:
                    t_img = self.asset_mgr.get_tile_surface(m.tile)
                    if t_img is not None:
                        surface.blit(t_img, (px, py))
                        blitted = True
                except Exception:
                    pass

            if not blitted:
                rect = pygame.Rect(px + 1, py + 1, TILE_SIZE - 2, TILE_SIZE - 2)
                pygame.draw.rect(surface, EGA_BRIGHT_RED, rect)
                txt = font.render(m.name[:1], True, EGA_WHITE)
                surface.blit(txt, (px + 3, py + 1))

        # Render dying monsters during their hit burst / attack animation
        for dm in self.dying_monsters:
            px = dm["x"] * TILE_SIZE
            py = dm["y"] * TILE_SIZE
            blitted = False
            if self.asset_mgr is not None:
                try:
                    t_img = self.asset_mgr.get_tile_surface(dm["tile"])
                    if t_img is not None:
                        surface.blit(t_img, (px, py))
                        blitted = True
                except Exception:
                    pass

            if not blitted:
                rect = pygame.Rect(px + 1, py + 1, TILE_SIZE - 2, TILE_SIZE - 2)
                pygame.draw.rect(surface, EGA_BRIGHT_RED, rect)
                txt = font.render(dm["name"][:1], True, EGA_WHITE)
                surface.blit(txt, (px + 3, py + 1))

    def _render_players(self, surface: pygame.Surface) -> None:
        font = get_hud_font(size=12)
        for p_idx, (px, py) in self.arena.player_positions.items():
            screen_x = px * TILE_SIZE
            screen_y = py * TILE_SIZE
            is_active = (p_idx == self.arena.active_party_member_idx)

            blitted = False
            member = self.party.get_member(p_idx)
            if self.asset_mgr is not None and member is not None:
                try:
                    t_name = getattr(member.profession, "tile", "fighter")
                    t_img = self.asset_mgr.get_tile_surface(t_name)
                    if t_img is not None:
                        surface.blit(t_img, (screen_x, screen_y))
                        blitted = True
                except Exception:
                    pass

            if not blitted:
                color = EGA_BRIGHT_GREEN if is_active else EGA_BRIGHT_CYAN
                rect = pygame.Rect(screen_x + 1, screen_y + 1, TILE_SIZE - 2, TILE_SIZE - 2)
                pygame.draw.rect(surface, color, rect)
                char_label = str(p_idx + 1)
                txt = font.render(char_label, True, EGA_BLACK)
                surface.blit(txt, (screen_x + 4, screen_y + 1))

            # Highlight active member with yellow border
            if is_active:
                pygame.draw.rect(
                    surface,
                    EGA_YELLOW,
                    pygame.Rect(screen_x, screen_y, TILE_SIZE, TILE_SIZE),
                    1,
                )

    def _render_grid_fallback(self, surface: pygame.Surface) -> None:
        for y in range(COMBAT_HEIGHT):
            for x in range(COMBAT_WIDTH):
                rect = pygame.Rect(x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE)
                pygame.draw.rect(surface, EGA_DARK_GRAY, rect, 1)
