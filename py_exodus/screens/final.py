"""Castle of Exodus confrontation, victory fanfare, and epilogue sequence."""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Any

import pygame

from py_exodus.screens.base import BaseScreen
from py_exodus.ui.text_log import (
    EGA_BLACK,
    EGA_BRIGHT_CYAN,
    EGA_BRIGHT_GREEN,
    EGA_BRIGHT_RED,
    EGA_DARK_GRAY,
    EGA_LIGHT_GRAY,
    EGA_WHITE,
    EGA_YELLOW,
    get_hud_font,
)

if TYPE_CHECKING:
    from py_exodus.entities.party import Party

EPILOGUE_TEXT = (
    "And so it came to pass\n\n"
    "that on this day\n\n"
    "EXODUS,\n\n"
    "hell-born incarnate of evil,\n\n"
    "was vanquished from Sosaria.\n\n"
    "What now lies ahead\n\n"
    "in the ULTIMA saga\n\n"
    "can only be pure speculation!\n\n"
    "Onward to ULTIMA IV!"
)

CARD_ORDER = ["love", "sol", "moons", "death"]
CARD_NAME_TO_INDEX = {
    "love": 0,
    "sol": 1,
    "moon": 2,
    "moons": 2,
    "death": 3,
}


class FinalScreen(BaseScreen):
    """Exodus confrontation sequence and victory epilogue.

    Handles inserting the 4 cards (Love, Sol, Moons, Death) into the four machine
    panels of Exodus in the correct sequence. On vanquishing Exodus, triggers
    screen shake, crumbling destruction, victory fanfare, and scrolling epilogue.
    """

    def __init__(
        self,
        party: Party | None = None,
        return_screen: BaseScreen | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(return_screen=return_screen, **kwargs)
        self.party = party
        self.panels_inserted: list[str] = []
        self.victory: bool = False
        self.screen_shake: bool = False
        self.shake_timer: float = 0.0
        self.shake_intensity: float = 0.0
        self.shake_offset: tuple[int, int] = (0, 0)
        self.fanfare_played: bool = False
        self.last_message: str = ""
        self.log_messages: list[str] = [
            "You stand before the great machine of EXODUS!",
            "Four card slots pulse with dark energy...",
        ]

        # Epilogue text scrolling
        self.epilogue_text = EPILOGUE_TEXT
        self.scroll_y: float = 220.0
        self.scroll_speed: float = 24.0  # pixels per second
        self.elapsed_time: float = 0.0

        # Crumbling debris particles
        self.particles: list[list[float]] = []  # [x, y, dx, dy, color_idx]

    def _normalize_card(self, card_name: str) -> str:
        """Normalize card string to standard name."""
        c = card_name.lower().strip()
        if c in ("moon", "moons"):
            return "moons"
        return c

    def insert_card(self, card_name: str, member_idx: int = 0) -> bool:
        """Attempt to insert a card into the next panel of Exodus.

        Checks sequence: Love -> Sol -> Moons -> Death.
        Consumes card from party member. If out of sequence, triggers spirit shock.
        """
        c_norm = self._normalize_card(card_name)
        card_idx = CARD_NAME_TO_INDEX.get(c_norm)

        # Verify party member ownership if party is provided
        member = None
        if self.party and 0 <= member_idx < len(self.party.members):
            member = self.party.get_member(member_idx)
            char = getattr(member, "player", member)
            if (
                card_idx is not None
                and hasattr(char, "cards")
                and card_idx < len(char.cards)
                and char.cards[card_idx] <= 0
            ):
                msg = f"None owned! You do not have the Card of {c_norm.capitalize()}."
                self.last_message = msg
                self.log_messages.append(msg)
                return False

        # Determine expected card in sequence
        next_step = len(self.panels_inserted)
        if next_step >= len(CARD_ORDER):
            return True

        expected_card = CARD_ORDER[next_step]

        if c_norm == expected_card:
            # Correct card!
            self.panels_inserted.append(c_norm)

            # Consume card from member inventory
            if member is not None and card_idx is not None:
                char = getattr(member, "player", member)
                if card_idx < len(char.cards):
                    char.cards[card_idx] = max(0, char.cards[card_idx] - 1)

            msg = f"The Card of {c_norm.capitalize()} clicks into panel {next_step + 1}!"
            self.last_message = msg
            self.log_messages.append(msg)

            # Check for total victory
            if len(self.panels_inserted) == len(CARD_ORDER):
                self._trigger_victory()

            return True
        else:
            # Out of sequence error / spirit retribution!
            msg = "Spirits arise! Shock strikes the party!"
            self.last_message = msg
            self.log_messages.append(msg)

            if member is not None:
                char = getattr(member, "player", member)
                char.hp = max(0, char.hp - 50)

            return False

    def _trigger_victory(self) -> None:
        """Activate victory fanfare, screen shake, and epilogue narration."""
        self.victory = True
        self.screen_shake = True
        self.shake_timer = 6.0
        self.shake_intensity = 6.0
        self.fanfare_played = True
        self.scroll_y = 220.0

        self.log_messages.append("EXODUS ROARS AS THE MACHINE CRUMBLES!")
        self.log_messages.append("Sosaria is saved from the great darkness!")

        # Spawn crumbling stone particles
        for _ in range(40):
            self.particles.append([
                random.uniform(50, 270),
                random.uniform(20, 100),
                random.uniform(-30, 30),
                random.uniform(40, 120),
                random.choice([0, 1, 2]),
            ])

    def handle_event(self, event: pygame.event.Event) -> None:
        """Handle keyboard input for card insertion and epilogue navigation."""
        if event.type != pygame.KEYDOWN:
            return

        if event.key == pygame.K_ESCAPE:
            self.exit_screen()
            return

        if not self.victory:
            # Keyboard shortcuts for inserting cards
            if event.key in (pygame.K_l,):
                self.insert_card("love")
            elif event.key in (pygame.K_s,):
                self.insert_card("sol")
            elif event.key in (pygame.K_m,):
                self.insert_card("moons")
            elif event.key in (pygame.K_d,):
                self.insert_card("death")
        else:
            # During epilogue, space or enter skips to end / exits
            if event.key in (pygame.K_SPACE, pygame.K_RETURN):
                self.exit_screen()

    def update(self, dt: float) -> None:
        """Update screen shake, particle physics, and scrolling text."""
        self.elapsed_time += dt

        if self.shake_timer > 0:
            self.shake_timer = max(0.0, self.shake_timer - dt)
            decay = self.shake_timer / 6.0
            amp = self.shake_intensity * decay
            self.shake_offset = (
                int(math.sin(self.elapsed_time * 40.0) * amp),
                int(math.cos(self.elapsed_time * 35.0) * amp),
            )
            if self.shake_timer <= 0:
                self.screen_shake = False
                self.shake_offset = (0, 0)

        # Update crumbling debris particles
        for p in self.particles:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[3] += 120.0 * dt  # Gravity

        # Scroll epilogue text upward
        if self.victory:
            self.scroll_y -= self.scroll_speed * dt

    def render(self, surface: pygame.Surface) -> None:
        """Render confrontation chamber or victory epilogue."""
        width = surface.get_width()
        height = surface.get_height()

        # Target render surface to allow shake offset
        target_surf = pygame.Surface((width, height))
        target_surf.fill(EGA_BLACK)

        font = get_hud_font(16)
        small_font = get_hud_font(12)

        if not self.victory:
            # Draw Chamber of Exodus
            title_surf = font.render("CASTLE OF EXODUS - INNER SANCTUM", True, EGA_BRIGHT_RED)
            target_surf.blit(title_surf, (width // 2 - title_surf.get_width() // 2, 10))

            # Machine of Exodus visual representation
            machine_rect = pygame.Rect(width // 2 - 120, 36, 240, 70)
            pygame.draw.rect(target_surf, (40, 10, 10), machine_rect)
            pygame.draw.rect(target_surf, EGA_BRIGHT_RED, machine_rect, 2)

            mach_label = font.render("=== EXODUS MACHINE ===", True, EGA_YELLOW)
            target_surf.blit(mach_label, (width // 2 - mach_label.get_width() // 2, 42))

            # Render 4 Card Panels
            panel_w, panel_h = 48, 36
            start_x = width // 2 - 110
            for i, card_type in enumerate(CARD_ORDER):
                px = start_x + i * 56
                py = 64
                is_filled = i < len(self.panels_inserted)

                rect = pygame.Rect(px, py, panel_w, panel_h)
                border_color = EGA_BRIGHT_GREEN if is_filled else EGA_DARK_GRAY
                fill_color = (0, 80, 0) if is_filled else (20, 20, 20)

                pygame.draw.rect(target_surf, fill_color, rect)
                pygame.draw.rect(target_surf, border_color, rect, 1)

                label = small_font.render(f"P{i + 1}", True, EGA_WHITE)
                target_surf.blit(label, (rect.centerx - label.get_width() // 2, py + 2))

                status_txt = card_type.upper() if is_filled else "EMPTY"
                status_color = EGA_YELLOW if is_filled else EGA_DARK_GRAY
                status_surf = small_font.render(status_txt[:5], True, status_color)
                target_surf.blit(status_surf, (rect.centerx - status_surf.get_width() // 2, py + 18))

            # Prompt instructions
            prompt = font.render("Insert card: [L]ove  [S]ol  [M]oons  [D]eath", True, EGA_BRIGHT_CYAN)
            target_surf.blit(prompt, (width // 2 - prompt.get_width() // 2, 114))

            # Message log at bottom
            y_log = height - 50
            for msg in self.log_messages[-3:]:
                m_surf = small_font.render(msg, True, EGA_WHITE)
                target_surf.blit(m_surf, (16, y_log))
                y_log += 14

        else:
            # VICTORY EPILOGUE
            # Draw crumbling debris particles
            p_colors = [EGA_YELLOW, EGA_BRIGHT_RED, EGA_LIGHT_GRAY]
            for p in self.particles:
                color = p_colors[int(p[4]) % len(p_colors)]
                pygame.draw.circle(target_surf, color, (int(p[0]), int(p[1])), 2)

            # Render scrolling epilogue text lines
            lines = self.epilogue_text.split("\n")
            cur_y = self.scroll_y
            for line in lines:
                if line.strip():
                    color = EGA_YELLOW if "EXODUS" in line or "ULTIMA" in line else EGA_WHITE
                    line_surf = font.render(line, True, color)
                    target_surf.blit(line_surf, (width // 2 - line_surf.get_width() // 2, int(cur_y)))
                cur_y += 18

            # Skip hint at bottom
            skip_surf = small_font.render("[SPACE / ESC] Continue", True, EGA_DARK_GRAY)
            target_surf.blit(skip_surf, (width // 2 - skip_surf.get_width() // 2, height - 16))

        # Blit target surface with shake offset
        ox, oy = self.shake_offset
        surface.blit(target_surf, (ox, oy))
