"""Castle of Exodus: the four Cards, then LairWare's ending.

The ending follows LairWare's INSERT (UltimaMisc.c:2357-2424): the
congratulations in the message window, 21 colour flashes over the map with
a hit on each, then the WinText epilogue fading in, a key, and the fade
out. Between the flashes and the epilogue sits our own victory page
(user-approved design, 2026-11-25): EXODUS VANQUISHED under the intro's
stalactites, LairWare's congratulations and the four heroes.
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

import pygame

from py_exodus.assets import MAP_NAME_TO_ID
from py_exodus.entities.party import PartyDeathException
from py_exodus.screens.base import BaseScreen
from py_exodus.ui.pixel_font import BLOCK, LOGO, SERIF, TINY, render_banner
from py_exodus.ui.roster_view import sprite as class_sprite
from py_exodus.ui.text_log import (
    EGA_BLACK,
    EGA_BRIGHT_CYAN,
    EGA_BRIGHT_GREEN,
    EGA_BRIGHT_RED,
    EGA_DARK_GRAY,
    EGA_WHITE,
    EGA_YELLOW,
    get_hud_font,
)

if TYPE_CHECKING:
    from py_exodus.assets import AssetManager
    from py_exodus.audio import AudioManager
    from py_exodus.entities.party import Party
    from py_exodus.world.map import GameMap

TICK = 1 / 60.0  # a LairWare tick

# The congratulations (UltimaMisc.c:2363-2379): Messages 255 (the modern
# appearance's wording), the move count, then Message 242.
LW_CONGRATULATIONS = "CONGRATULATIONS! Thou hast compleated EXODUS: ULTIMA III in"
LW_MOVES = " MOVES"
LW_REPORT = "REPORT THY FEAT!"
#: The same words set out on the victory page, in capitals.
PAGE_LINES = ("CONGRATULATIONS!", "THOU HAST COMPLEATED", "EXODUS: ULTIMA III", "IN")

# The flashes (UltimaMisc.c:2392-2404): `for (input = 0; input <= 20; ...)`
# paints the map pane a random colour, plays Hit and sleeps 10 ticks.
FLASH_COUNT = 21
FLASH_TICKS = 10

# The epilogue fades (UltimaMisc.c:2407-2423): 16 greys up from 0 in steps
# of 16, a key, then 16 greys down from 255. A step up is ThreadSleepTicks(1)
# plus the wait for the next tick; a step down is the wait alone.
FADE_STEPS = 16
FADE_IN_TICKS = 2
FADE_OUT_TICKS = 1

#: WinText (UltimaText.c:736-745), LairWare's twenty-column lines exactly.
EPILOGUE_LINES = (
    "   And so it came to",
    "pass  that  on  this",
    "day EXODUS,hell-born",
    "incarnate  of  evil,",
    "was vanquished  from",
    "SOSARIA.   What  now",
    "lies  ahead  in  the",
    "ULTIMA saga can only",
    "be pure speculation!",
    "Onward to ULTIMA IV!",
)

# The ending is laid out on a 320x200 page, drawn at 3x on the big screen.
PAGE_W, PAGE_H = 320, 200
MAP_PANE = 176  # the map pane of the game screens, top left
STALACTITES_ART = ("graphics", "title", "stalactites.png")
# The colours of the pyExodus title art.
PAGE_WHITE = (255, 255, 255)
PAGE_GREY = (170, 170, 170)
PAGE_YELLOW = (238, 238, 119)


def congratulation_lines(party: Any) -> list[str]:
    """LairWare's congratulations for the message window, in its order:
    the words, the party's move count and "MOVES", "REPORT THY FEAT!"."""
    moves = int(getattr(party, "moves", 0) or 0)
    return [LW_CONGRATULATIONS, f"{moves}{LW_MOVES}", LW_REPORT]


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
            final_scr = FinalScreen(
                party=screen.party,
                audio=getattr(screen, "audio", None),
                asset_mgr=getattr(screen, "asset_mgr", None),
            )
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
                for line in congratulation_lines(screen.party):
                    screen.text_log.add_message(line)
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
    """The Exodus machine's card rules, and the ending once it falls.

    ``insert_card`` is the shared entry point for the INSERT flow (overworld
    and town OtherCommand) — Java keeps insertion on the EXODUS map
    (``SecondaryInputProcessor.java:664-701``) and shows this screen only once
    all four cards are registered. A card at its own panel, in LairWare's
    order Love, Sol, Moons, Death (UltimaMisc.c:2333-2343), sets the
    ``exodusCardsStatus`` bit; anything else costs the inserting member
    ``health + 1`` (lethal).

    The ending runs through ``phase``: ``flash`` (LairWare's 21 flashes over
    the screen this one was pushed on; no key shortens them), ``page`` (the
    victory page, until a key), ``fade_in``, ``epilogue`` (until a key) and
    ``fade_out``, which ends at the title.
    """

    def __init__(
        self,
        party: Party | None = None,
        return_screen: BaseScreen | None = None,
        audio: AudioManager | None = None,
        asset_mgr: Any = None,
        rng: random.Random | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(return_screen=return_screen, **kwargs)
        self.party = party
        self.audio = audio
        # Handed on to the title by return_to_title: without it the next
        # Journey Onward overworld has no renderer and draws black.
        self.asset_mgr = asset_mgr
        self.victory: bool = False
        self.last_message: str = ""
        self.log_messages: list[str] = [
            "You stand before the great machine of EXODUS!",
            "Four card slots pulse with dark energy...",
        ]

        # The ending. The flash colours come from their own generator, so
        # the ending never moves the game's random stream.
        self.phase: str | None = None
        self.rng = rng if rng is not None else random.Random()
        self.flash_colours: list[tuple[int, int, int]] = []
        self.grey: int = 0  # the epilogue's brightness, LairWare's 0-255
        self._clock: float = 0.0
        #: What the last render of the page or epilogue drew: (name, rect).
        self.layout: list[tuple[str, pygame.Rect]] = []
        self._stalactites: pygame.Surface | None = None
        self._stalactites_tried = False

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

        Java truth: ``exodus/SecondaryInputProcessor.java:664-701`` — the correct
        panel (Love x30, Sol x31, Moons x32, Death x33, all y 12) sets the
        ``exodusCardsStatus`` bit, a wrong panel costs the member ``health + 1``
        (lethal, raises ``PartyDeathException`` when it kills the last living
        member). All four bits set => victory.

        The card is never used up (LairWare UltimaMisc.c:2328-2343 only tests
        its bit), at the right panel or the wrong one.
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

        panel_x, mask = CARD_PANELS[name]
        x, y = pos if pos is not None else (self.party.x, self.party.y)
        # LairWare (UltimaMisc.c:2333-2343): the card must match its panel
        # AND be the next of Love, Sol, Moons, Death (lastCard); anything
        # else, a repeated card included, kills the member.
        in_order = self.card_status == mask - 1
        if x == panel_x and y == PANEL_Y and in_order:
            # LairWare INSERT (UltimaMisc.c:2328-2343) tests the card bit and
            # never clears it: the member keeps the card, right panel or not.
            self.party.exodus_cards_status = self.card_status | mask
            if self.audio is not None:
                self.audio.play_sfx("DivineMed")
            self._log(f"The Card of {name.capitalize()} vanishes into the machine!")
            if all_cards_inserted(self.party.exodus_cards_status):
                self._trigger_victory()
            return True

        if self.audio is not None:
            self.audio.play_sfx("AncientSpirits")
        self._log(f"The machine screams! Spirits strike {member.name}!")
        member.apply_damage(char.hp + 1, False)
        return False

    def _trigger_victory(self) -> None:
        """Exodus falls: set the win flag and start the ending."""
        self.victory = True
        # LW truth: landing the final card sets the beat-Exodus flag
        # (UltimaMisc.c:2359 — Party[16] = 1). No rule reads it any more
        # (the game ends here, user ruling 2026-11-25); autoplay, batches
        # and the trace read it as the win.
        self.party.exodus_defeated = 1
        # gSongCurrent = gSongNext = 10 (UltimaMisc.c:2362): the fanfare.
        if self.audio is not None:
            self.audio.play_music("fanfare")
        self._enter("flash")

    # ------------------------------------------------------------------
    # The ending's beats
    # ------------------------------------------------------------------
    def _enter(self, phase: str) -> None:
        self.phase = phase
        self._clock = 0.0

    def _flash(self) -> None:
        """One flash (UltimaMisc.c:2394-2403): a random colour and a hit."""
        self.flash_colours.append(
            (self.rng.randrange(256), self.rng.randrange(256), self.rng.randrange(256))
        )
        if self.audio is not None:
            self.audio.play_sfx("Hit")

    def handle_event(self, event: pygame.event.Event) -> None:
        """Card shortcuts before the fall; after it, the ending's two key waits."""
        if self.victory:
            # LairWare waits for a key or a click (WaitKeyMouse) once the
            # epilogue is up; the victory page waits the same way. Keys
            # pressed during the flashes or a fade do nothing and are not
            # kept. User ruling 2026-11-25: the game ends when Exodus
            # falls, so the fade out goes to the title; nothing is saved.
            if event.type not in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                return
            if self.phase == "page":
                self._enter("fade_in")
                self.grey = 0
            elif self.phase == "epilogue":
                self._enter("fade_out")
                self.grey = 255
            return

        if event.type != pygame.KEYDOWN:
            return

        if event.key == pygame.K_ESCAPE:
            self.exit_screen()
            return

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

    def update(self, dt: float) -> None:
        """Advance the ending on LairWare's clock."""
        if not self.victory:
            return
        self._clock += dt
        eps = 1e-9
        if self.phase == "flash":
            step = FLASH_TICKS * TICK
            while (
                len(self.flash_colours) < FLASH_COUNT
                and self._clock + eps >= len(self.flash_colours) * step
            ):
                self._flash()
            if self._clock + eps >= FLASH_COUNT * step:
                self._enter("page")
        elif self.phase == "fade_in":
            step = int((self._clock + eps) / (FADE_IN_TICKS * TICK))
            if step >= FADE_STEPS:
                # LairWare's last step up is WinText(240), and there it waits.
                self.grey = 16 * (FADE_STEPS - 1)
                self._enter("epilogue")
            else:
                self.grey = 16 * step
        elif self.phase == "fade_out":
            step = int((self._clock + eps) / (FADE_OUT_TICKS * TICK))
            if step >= FADE_STEPS:
                self.grey = 0
                self.phase = "done"
                self.return_to_title(won=True)
            else:
                self.grey = 255 - 16 * step

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def render(self, surface: pygame.Surface) -> None:
        """The machine before the fall; after it, the ending's current beat."""
        if not self.victory:
            self._render_machine(surface)
        elif self.phase == "flash":
            self._render_flash(surface)
        elif self.phase == "page":
            self._render_page(surface)
        else:
            self._render_epilogue(surface)

    @staticmethod
    def _page_frame(surface: pygame.Surface) -> tuple[int, int, int]:
        """(scale, x, y) of the 320x200 page centred on the surface."""
        w, h = surface.get_size()
        scale = 3 if w >= 640 else 1
        return scale, (w - PAGE_W * scale) // 2, (h - PAGE_H * scale) // 2

    def _render_flash(self, surface: pygame.Surface) -> None:
        """The game screen under the ending, its map pane flashed.

        LairWare adds each colour to the pane with QuickDraw's addOver and
        leaves the last one there; here every flash goes on a fresh frame.
        """
        backdrop = self.return_screen
        if backdrop is not None:
            backdrop.render(surface)
        else:
            surface.fill(EGA_BLACK)
        if not self.flash_colours:
            return
        scale = 3 if surface.get_width() >= 640 else 1
        pane = pygame.Rect(0, 0, MAP_PANE * scale, MAP_PANE * scale).clip(surface.get_rect())
        surface.fill(self.flash_colours[-1], pane, special_flags=pygame.BLEND_RGB_ADD)

    def _stalactite_art(self) -> pygame.Surface | None:
        if not self._stalactites_tried:
            self._stalactites_tried = True
            if self.asset_mgr is not None:
                from py_exodus.assets import load_image_surface

                try:
                    self._stalactites = load_image_surface(
                        self.asset_mgr.resolve_path(*STALACTITES_ART)
                    )
                except (OSError, pygame.error):
                    self._stalactites = None
        return self._stalactites

    def _render_page(self, surface: pygame.Surface) -> None:
        """The victory page: EXODUS VANQUISHED, LairWare's congratulations
        with the move count, the party, and REPORT THY FEAT!"""
        surface.fill(EGA_BLACK)
        scale, ox, oy = self._page_frame(surface)
        self.layout = []

        def put(name: str, img: pygame.Surface, y: int, cx: float = PAGE_W / 2) -> None:
            """Blit ``img`` centred on page column ``cx`` with its top at page row ``y``."""
            rect = img.get_rect()
            rect.midtop = (ox + round(cx * scale), oy + y * scale)
            surface.blit(img, rect)
            self.layout.append((name, rect))

        art = self._stalactite_art()
        if art is not None:
            if scale != 1:
                art = pygame.transform.scale(
                    art, (art.get_width() * scale, art.get_height() * scale)
                )
            put("stalactites", art, 0)

        put("EXODUS", render_banner(LOGO, "EXODUS", scale, 2), 21)
        put("VANQUISHED", render_banner(LOGO, "VANQUISHED", scale), 46)
        y = 64
        for line in PAGE_LINES:
            put(line, BLOCK.render(line, PAGE_WHITE, scale), y)
            y += 10
        moves = int(getattr(self.party, "moves", 0) or 0)
        put("moves", render_banner(LOGO, f"{moves:,}", scale), y)
        put(LW_MOVES.strip(), BLOCK.render(LW_MOVES.strip(), PAGE_WHITE, scale), y + 16)

        members = list(getattr(self.party, "members", None) or [])[:4]
        for i, member in enumerate(members):
            cx = PAGE_W * (2 * i + 1) / (2 * len(members))
            char = getattr(member, "player", member)
            sprite = class_sprite(self.asset_mgr, getattr(char, "profession", None), 16 * scale)
            if sprite is not None:
                put(f"sprite {i}", sprite, 135, cx)
            name = str(getattr(member, "name", "") or "")[:12]
            put(f"name {i}", BLOCK.render(name, PAGE_WHITE, scale), 154, cx)
            job = str(getattr(getattr(char, "profession", None), "name", "") or "?")
            who = f"{job.replace('_', ' ')} LV {int(getattr(char, 'level', 0) or 0)}"
            put(f"class {i}", TINY.render(who, PAGE_GREY, scale), 164, cx)

        put(LW_REPORT, BLOCK.render(LW_REPORT, PAGE_YELLOW, scale), 185)

    def _render_epilogue(self, surface: pygame.Surface) -> None:
        """WinText: the ten lines at the current grey, the last in yellow."""
        surface.fill(EGA_BLACK)
        scale, ox, oy = self._page_frame(surface)
        self.layout = []
        if self.grey <= 0:
            return
        cols = max(len(line) for line in EPILOGUE_LINES)
        left = (PAGE_W - SERIF.width(" " * cols)) // 2
        for k, line in enumerate(EPILOGUE_LINES):
            base = PAGE_YELLOW if k == len(EPILOGUE_LINES) - 1 else PAGE_WHITE
            colour = tuple(c * self.grey // 255 for c in base)
            img = SERIF.render(line, colour, scale)
            rect = img.get_rect(topleft=(ox + left * scale, oy + (10 + 18 * k) * scale))
            surface.blit(img, rect)
            self.layout.append((line, rect))

    def _render_machine(self, surface: pygame.Surface) -> None:
        """The four card panels (before the fall)."""
        width = surface.get_width()
        height = surface.get_height()
        surface.fill(EGA_BLACK)

        font = get_hud_font(16)
        small_font = get_hud_font(12)

        title_surf = font.render("CASTLE OF EXODUS - INNER SANCTUM", True, EGA_BRIGHT_RED)
        surface.blit(title_surf, (width // 2 - title_surf.get_width() // 2, 10))

        # Machine of Exodus visual representation
        machine_rect = pygame.Rect(width // 2 - 120, 36, 240, 70)
        pygame.draw.rect(surface, (40, 10, 10), machine_rect)
        pygame.draw.rect(surface, EGA_BRIGHT_RED, machine_rect, 2)

        mach_label = font.render("=== EXODUS MACHINE ===", True, EGA_YELLOW)
        surface.blit(mach_label, (width // 2 - mach_label.get_width() // 2, 42))

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

            pygame.draw.rect(surface, fill_color, rect)
            pygame.draw.rect(surface, border_color, rect, 1)

            label = small_font.render(f"P{i + 1}", True, EGA_WHITE)
            surface.blit(label, (rect.centerx - label.get_width() // 2, 66))

            status_txt = card_type.upper() if is_filled else "EMPTY"
            status_color = EGA_YELLOW if is_filled else EGA_DARK_GRAY
            status_surf = small_font.render(status_txt[:5], True, status_color)
            surface.blit(status_surf, (rect.centerx - status_surf.get_width() // 2, 82))

        # Prompt instructions
        prompt = font.render("Insert card: [L]ove  [S]ol  [M]oons  [D]eath", True, EGA_BRIGHT_CYAN)
        surface.blit(prompt, (width // 2 - prompt.get_width() // 2, 114))

        # Message log at bottom
        y_log = height - 50
        for msg in self.log_messages[-3:]:
            m_surf = small_font.render(msg, True, EGA_WHITE)
            surface.blit(m_surf, (16, y_log))
            y_log += 14
