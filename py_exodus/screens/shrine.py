"""Ambrosia Shrine Screen for py-exodus."""
from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING, Any

import pygame

from py_exodus.constants import (
    TILE_SIZE,
    VIEWPORT_TILES,
)
from py_exodus.screens.base import BaseScreen
from py_exodus.ui.text_log import (
    EGA_BLACK,
    EGA_BRIGHT_CYAN,
    EGA_BRIGHT_GREEN,
    EGA_DARK_GRAY,
    EGA_WHITE,
    EGA_YELLOW,
    get_hud_font,
)

if TYPE_CHECKING:
    from py_exodus.assets import AssetManager
    from py_exodus.entities.party import Party
    from py_exodus.world.map import GameMap


def _normalize_stat(stat_name: str) -> tuple[str, str, str]:
    """Map user/map stat name to (display_name, character_attr, race_cap_attr)."""
    s = stat_name.lower().strip()
    if "wis" in s:
        return "Wisdom", "wisdom", "max_wis"
    if "dex" in s:
        return "Dexterity", "dexterity", "max_dex"
    if "int" in s:
        return "Intelligence", "intelligence", "max_int"
    return "Strength", "strength", "max_str"


class ShrineScreen(BaseScreen):
    """Ambrosia Shrine screen for meditating and boosting stats.

    Handles 11x11 shrine map rendering, member selection, and 100 gold donations
    to increase Wisdom, Dexterity, Intelligence, or Strength up to race caps.
    """

    STATE_WALK = "walk"
    STATE_WHO = "who"
    STATE_DONATE = "donate"
    STATE_DONE = "done"

    def __init__(
        self,
        party: Party,
        stat_name: str = "strength",
        return_screen: BaseScreen | None = None,
        asset_mgr: AssetManager | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(return_screen=return_screen, **kwargs)
        self.party = party
        self.stat_display, self.stat_attr, self.stat_cap_attr = _normalize_stat(stat_name)
        self.asset_mgr = asset_mgr

        self.selected_member_idx: int = 0
        self.state: str = self.STATE_WHO
        self.log_messages: list[str] = [
            "You enter the ancient shrine and sit before the altar...",
            "Who will meditate? (1-4)",
        ]
        self.last_message: str = ""

        # Map and avatar positioning
        self.game_map: GameMap | None = None
        self.avatar_x: int = 5
        self.avatar_y: int = 6  # At altar
        self.anim_timer: float = 0.0

        if self.asset_mgr is not None:
            self._load_shrine_map()

    def _load_shrine_map(self) -> None:
        """Attempt loading shrine map JSON via MapLoader."""
        try:
            from py_exodus.world.loader import MapLoader

            loader = MapLoader(self.asset_mgr)
            self.game_map = loader.load_shrine_map("shrine.json")
        except (FileNotFoundError, ValueError, OSError):
            self.game_map = None

    def donate(self, member_idx: int, amount: int = 1) -> bool:
        """Donate 100 gold per point to boost character stat up to racial cap.

        Java truth: ``exodus/ShrineScreen.java:200-231`` — the donation is
        debited from the *selected member's* own purse via
        ``CharacterRecord.adjustGold`` (gold is per member), and the check
        against a too-poor player is ``You cannot cheat the gods!``.

        Returns True if donation succeeded, False if insufficient gold or invalid member.
        """
        member = self.party.get_member(member_idx)
        if member is None:
            self.log_messages.append("Who else?")
            self.last_message = "Who else?"
            return False

        char = getattr(member, "player", member)
        cost = amount * 100
        if getattr(char, "gold", 0) < cost:
            self.log_messages.append("You cannot cheat the gods!")
            self.last_message = "You cannot cheat the gods!"
            return False

        current_stat = getattr(char, self.stat_attr)
        max_stat = getattr(char.race, self.stat_cap_attr)

        char.adjust_gold(-cost)
        new_stat = min(current_stat + amount, max_stat)
        setattr(char, self.stat_attr, new_stat)

        # Java truth: ShrineScreen.java:222 — the success message is exactly
        # "Shazam!".
        self.log_messages.append("Shazam!")
        self.last_message = "Shazam!"
        return True

    def handle_event(self, event: pygame.event.Event) -> None:
        """Handle player key events for member selection and donation."""
        if event.type != pygame.KEYDOWN:
            return

        if event.key == pygame.K_ESCAPE:
            self.log_messages.append("Begone then!")
            self.last_message = "Begone then!"
            self.exit_screen()
            return

        if self.state == self.STATE_WHO:
            # Keys 1-4 for party members
            if event.unicode in ("1", "2", "3", "4"):
                idx = int(event.unicode) - 1
                if 0 <= idx < len(self.party.members):
                    self.selected_member_idx = idx
                    member = self.party.get_member(idx)
                    name = member.name if member else f"Member {idx + 1}"
                    self.state = self.STATE_DONATE
                    self.log_messages.append(f"{name}: Offering * 100? (Press 1-9 for amount, ESC to leave)")
                else:
                    self.log_messages.append("Who else?")
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self.selected_member_idx = 0
                self.state = self.STATE_DONATE
                member = self.party.get_member(0)
                name = member.name if member else "Hero"
                self.log_messages.append(f"{name}: Offering * 100? (Press 1-9 for amount, ESC to leave)")

        elif self.state == self.STATE_DONATE:
            if event.unicode in "123456789":
                amt = int(event.unicode)
                # Java truth: ShrineScreen.java:207-231. An offer the member
                # cannot pay draws "You cannot cheat the gods!" and the shrine
                # stays open for another amount; a paid offer logs "Shazam!"
                # and returns to the overworld.
                if self.donate(self.selected_member_idx, amount=amt):
                    self.state = self.STATE_DONE
                    self.exit_screen()
            elif event.unicode == "0":
                self.log_messages.append("Begone then!")
                self.last_message = "Begone then!"
                self.state = self.STATE_DONE
                self.exit_screen()
            elif event.key in (pygame.K_RETURN, pygame.K_y):
                if self.donate(self.selected_member_idx, amount=1):
                    self.state = self.STATE_DONE
                    self.exit_screen()
            elif event.key == pygame.K_n:
                self.log_messages.append("Begone then!")
                self.state = self.STATE_DONE
                self.exit_screen()

        elif self.state == self.STATE_DONE:
            self.exit_screen()

    def update(self, dt: float) -> None:
        """Advance animation timer."""
        self.anim_timer += dt

    def render(self, surface: pygame.Surface) -> None:
        """Draw the 11x11 shrine chamber, altar, avatar, and HUD prompt."""
        width = surface.get_width()

        # Background fill
        surface.fill(EGA_BLACK)

        font = get_hud_font(16)
        small_font = get_hud_font(12)

        # Render 11x11 Map / Viewport on the left
        viewport_px = VIEWPORT_TILES * TILE_SIZE  # 176x176
        viewport_rect = pygame.Rect(8, 8, viewport_px, viewport_px)

        if self.game_map is not None and self.asset_mgr is not None:
            from py_exodus.ui.renderer import WorldRenderer

            renderer = WorldRenderer(self.asset_mgr)
            renderer.render_viewport(
                surface=surface,
                game_map=self.game_map,
                center_x=5,
                center_y=5,
                dest_pos=(viewport_rect.x, viewport_rect.y),
            )
        else:
            # Fallback simple decorative shrine view
            pygame.draw.rect(surface, (20, 20, 50), viewport_rect)
            pygame.draw.rect(surface, EGA_DARK_GRAY, viewport_rect, 1)

            # Draw altar at center
            altar_rect = pygame.Rect(
                viewport_rect.centerx - 16,
                viewport_rect.centery - 16,
                32,
                16,
            )
            pygame.draw.rect(surface, EGA_YELLOW, altar_rect)

            # Draw avatar in front of altar
            avatar_rect = pygame.Rect(
                viewport_rect.centerx - 8,
                viewport_rect.centery + 8,
                16,
                16,
            )
            pygame.draw.rect(surface, EGA_BRIGHT_CYAN, avatar_rect)

        # Right Column HUD (x = viewport_rect.right + 12 .. width - 8)
        col_x = viewport_rect.right + 12

        # Title
        title_surf = small_font.render("SHRINE OF", True, EGA_YELLOW)
        surface.blit(title_surf, (col_x, 8))
        stat_surf = font.render(self.stat_display.upper()[:10], True, EGA_YELLOW)
        surface.blit(stat_surf, (col_x, 20))

        # Party gold
        gold_surf = small_font.render(f"GOLD: {self.party.gold}", True, EGA_WHITE)
        surface.blit(gold_surf, (col_x, 38))

        # Member list & current stat
        y_offset = 52
        for i, m in enumerate(self.party.members):
            cur = getattr(m, self.stat_attr)
            cap = getattr(m.race, self.stat_cap_attr)
            color = EGA_BRIGHT_GREEN if i == self.selected_member_idx else EGA_WHITE
            line = f"{i + 1}:{m.name[:5]} {cur}/{cap}"
            text_surf = small_font.render(line, True, color)
            surface.blit(text_surf, (col_x, y_offset))
            y_offset += 13

        # Divider between party stats and message log in the right column
        pygame.draw.line(surface, EGA_DARK_GRAY, (col_x - 4, 108), (width - 8, 108))

        # Message Log and Prompts in right column (leaving 176x176 viewport unobstructed)
        lines: list[str] = []
        for msg in self.log_messages[-3:]:
            wrapped = textwrap.wrap(msg, width=17) or [msg]
            lines.extend(wrapped)

        log_y = 114
        for line in lines[-5:]:
            msg_surf = small_font.render(line, True, EGA_BRIGHT_CYAN)
            surface.blit(msg_surf, (col_x, log_y))
            log_y += 14
