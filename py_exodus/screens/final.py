"""Castle of Exodus confrontation, victory fanfare, and epilogue sequence."""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Any

import pygame

from py_exodus.assets import MAP_NAME_TO_ID
from py_exodus.entities.party import PartyDeathException
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
    from py_exodus.assets import AssetManager
    from py_exodus.audio import AudioManager
    from py_exodus.entities.party import Party
    from py_exodus.world.map import GameMap

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

# Render order of the four machine panels; insertion itself is order-free.
PANEL_DISPLAY = ["love", "sol", "moons", "death"]

# Java truth: exodus/SecondaryInputProcessor.java:664-668 — key L/S/M/D maps to
# card index, machine panel x, and exodusCardsStatus bit. Card rows are
# [DEATH, SOL, MOONS, LOVE] = cards[0..3] (Party.java:708-711).
CARD_NAME_TO_INDEX = {
    "death": 0,
    "sol": 1,
    "moon": 2,
    "moons": 2,
    "love": 3,
}
CARD_PANELS = {
    "love": (30, 0x1),
    "sol": (31, 0x2),
    "moons": (32, 0x4),
    "death": (33, 0x8),
}
CARD_LETTER_TO_NAME = {"l": "love", "s": "sol", "m": "moons", "d": "death"}
EXODUS_MAP_ID = MAP_NAME_TO_ID["EXODUS"]
ALL_CARDS_MASK = 0xF
PANEL_Y = 12


def is_exodus_map(map_id: int | str | None, game_map: Any = None) -> bool:
    """Whether the party is on the EXODUS map (Maps.EXODUS, id 2)."""
    if game_map is not None and str(getattr(game_map, "name", "")).upper() == "EXODUS":
        return True
    if map_id is None:
        return False
    if isinstance(map_id, str):
        return map_id.strip().upper() == "EXODUS"
    return map_id == EXODUS_MAP_ID


def is_machine_region(x: int, y: int) -> bool:
    """The four machine panels: x 30-33 at y 12 (SecondaryInputProcessor.java:614)."""
    return 30 <= x <= 33 and y == PANEL_Y


def all_cards_inserted(status: int) -> bool:
    """All four cards registered (FinalScreen.java:718-727 check in Java)."""
    return (status & ALL_CARDS_MASK) == ALL_CARDS_MASK


def apply_exodus_card_tiles(
    game_map: GameMap | None, asset_mgr: AssetManager | None, status: int
) -> None:
    """Cleared machine panels become floor tiles at (x, 11).

    Java truth: ``exodus/GameScreen.java:299-311`` — each set bit replaces the
    machine tile with ``floor`` on the EXODUS map (both at insertion time and
    on reload). Non-EXODUS maps are left untouched.
    """
    if not status or asset_mgr is None or not is_exodus_map(None, game_map):
        return
    floor = asset_mgr.get_tile_by_name("floor")
    if floor is None:
        return
    for mask, x in ((0x1, 30), (0x2, 31), (0x4, 32), (0x8, 33)):
        if status & mask:
            game_map.set_tile(x, 11, floor)


def prompt_insert_card(screen: BaseScreen, x: int, y: int) -> None:
    """Typed INSERT flow: gate, member prompt, card-letter prompt, insertion.

    Java truth: ``exodus/SecondaryInputProcessor.java:613-742`` — INSERT on the
    EXODUS machine region prompts "D, S, L, M:" and hands over to
    ``InsertCardInputAdapter``; elsewhere it answers "What?".
    """
    if not (
        is_exodus_map(getattr(screen, "map_id", None), getattr(screen, "game_map", None))
        and is_machine_region(x, y)
    ):
        screen.text_log.add_message("What?")
        return

    def _on_member(m_str: str) -> None:
        try:
            idx = int(m_str.strip()) - 1
        except ValueError:
            idx = -1
        member = screen.party.get_member(idx)
        if member is None:
            screen.text_log.add_message("Invalid member #!")
            return

        def _on_card(letter: str) -> None:
            card = CARD_LETTER_TO_NAME.get(letter.strip().lower())
            if card is None:
                screen.text_log.add_message("What?")
                return
            final_scr = FinalScreen(party=screen.party, audio=getattr(screen, "audio", None))
            try:
                inserted = final_scr.insert_card(card, member_idx=idx, pos=(x, y))
            except PartyDeathException:
                if final_scr.last_message:
                    screen.text_log.add_message(final_scr.last_message)
                screen.check_party_death()
                return
            if final_scr.last_message:
                screen.text_log.add_message(final_scr.last_message)
            if not inserted:
                return
            status = screen.party.exodus_cards_status
            apply_exodus_card_tiles(screen.game_map, screen.asset_mgr, status)
            if all_cards_inserted(status):
                if screen.manager is not None:
                    screen.manager.push_screen(final_scr)
                else:
                    screen.next_screen = final_scr
                    screen.is_finished = True

        screen.text_log.prompt("D, S, L, M: ", callback=_on_card, single_char=True)

    screen.text_log.prompt(
        "Which party member? (1-4): ", callback=_on_member, single_char=True
    )


class FinalScreen(BaseScreen):
    """Exodus confrontation panels and victory epilogue.

    ``insert_card`` is the shared entry point for the INSERT flow (overworld
    and town OtherCommand) — Java keeps insertion on the EXODUS map
    (``SecondaryInputProcessor.java:664-701``) and shows this screen only once
    all four cards are registered. Each of the four panels is independent:
    a card at its own panel sets the ``exodusCardsStatus`` bit, a card at a
    wrong panel costs the inserting member ``health + 1`` (lethal).
    """

    def __init__(
        self,
        party: Party | None = None,
        return_screen: BaseScreen | None = None,
        audio: AudioManager | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(return_screen=return_screen, **kwargs)
        self.party = party
        self.audio = audio
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

    def _log(self, msg: str) -> None:
        self.last_message = msg
        self.log_messages.append(msg)

    @property
    def card_status(self) -> int:
        """The party's exodusCardsStatus bits (0 without a party)."""
        if self.party is None:
            return 0
        return getattr(self.party, "exodus_cards_status", 0) & ALL_CARDS_MASK

    def _resolve_member(self, card_idx: int, member_idx: int | None):
        """The card-holding member named by member_idx, else any holder."""
        if self.party is None or not self.party.members:
            return None

        def holds(candidate) -> bool:
            char = getattr(candidate, "player", candidate)
            return (
                hasattr(char, "cards")
                and card_idx < len(char.cards)
                and char.cards[card_idx] > 0
            )

        if member_idx is not None:
            if 0 <= member_idx < len(self.party.members) and holds(
                self.party.get_member(member_idx)
            ):
                return self.party.get_member(member_idx)
            return None

        for candidate in self.party.members:
            if holds(candidate):
                return candidate
        return None

    def insert_card(
        self,
        card_name: str,
        member_idx: int | None = None,
        pos: tuple[int, int] | None = None,
    ) -> bool:
        """Insert a card into the machine panel the party stands on.

        Java truth: ``exodus/SecondaryInputProcessor.java:664-701`` — the card
        is consumed first; the correct panel (Love x30, Sol x31, Moons x32,
        Death x33, all y 12) sets the ``exodusCardsStatus`` bit, a wrong panel
        costs the member ``health + 1`` (lethal, raises ``PartyDeathException``
        when it kills the last living member). All four bits set => victory.
        """
        name = self._normalize_card(str(card_name))
        card_idx = CARD_NAME_TO_INDEX.get(name)
        if card_idx is None:
            self._log("What?")
            return False

        member = self._resolve_member(card_idx, member_idx)
        if member is None:
            self._log("None owned!")
            return False

        char = getattr(member, "player", member)
        char.cards[card_idx] -= 1

        panel_x, mask = CARD_PANELS[name]
        x, y = pos if pos is not None else (self.party.x, self.party.y)
        if x == panel_x and y == PANEL_Y:
            self.party.exodus_cards_status = self.card_status | mask
            if self.audio is not None:
                self.audio.play_sfx("DivineMed")
            self._log(f"The Card of {name.capitalize()} vanishes into the machine!")
            if all_cards_inserted(self.party.exodus_cards_status):
                self._trigger_victory()
            return True

        if self.audio is not None:
            self.audio.play_sfx("AncientSpirits")
        self._log(f"The wrong panel screams! Spirits strike {member.name}!")
        member.apply_damage(char.hp + 1, False)
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
            # Keyboard shortcuts for inserting cards (Java: L/S/M/D keys,
            # SecondaryInputProcessor.java:664-668)
            key_name = None
            if event.key == pygame.K_l:
                key_name = "love"
            elif event.key == pygame.K_s:
                key_name = "sol"
            elif event.key == pygame.K_m:
                key_name = "moons"
            elif event.key == pygame.K_d:
                key_name = "death"
            if key_name is not None:
                try:
                    self.insert_card(key_name)
                except PartyDeathException:
                    self.check_party_death()
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

            # Render 4 Card Panels (filled state from exodusCardsStatus bits)
            status = self.card_status
            panel_w, panel_h = 48, 36
            start_x = width // 2 - 110
            for i, card_type in enumerate(PANEL_DISPLAY):
                _panel_x, mask = CARD_PANELS[card_type]
                is_filled = bool(status & mask)

                rect = pygame.Rect(start_x + i * 56, 64, panel_w, panel_h)
                border_color = EGA_BRIGHT_GREEN if is_filled else EGA_DARK_GRAY
                fill_color = (0, 80, 0) if is_filled else (20, 20, 20)

                pygame.draw.rect(target_surf, fill_color, rect)
                pygame.draw.rect(target_surf, border_color, rect, 1)

                label = small_font.render(f"P{i + 1}", True, EGA_WHITE)
                target_surf.blit(label, (rect.centerx - label.get_width() // 2, 66))

                status_txt = card_type.upper() if is_filled else "EMPTY"
                status_color = EGA_YELLOW if is_filled else EGA_DARK_GRAY
                status_surf = small_font.render(status_txt[:5], True, status_color)
                target_surf.blit(status_surf, (rect.centerx - status_surf.get_width() // 2, 82))

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

        # Blit target surface with shake offset onto a cleared display surface
        surface.fill(EGA_BLACK)
        ox, oy = self.shake_offset
        surface.blit(target_surf, (ox, oy))
