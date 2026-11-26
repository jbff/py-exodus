"""Quick-reference cards: F3 the letter commands, F4 the spells.

A py-exodus addition (LairWare has no such card). The card is pushed over
the game screen like the Book of Lore, so the screen beneath gets no
``update`` while it is up: no idle pass, no wind or whirlpool clock, no
combat timers. The game is paused, as under Ztats.

``COMMANDS`` is the one table the card draws from; tests/test_quickref.py
checks its where-flags against each screen's key handler. ``SPELL_EFFECTS``
states each spell as the rules in combat/magic.py work it, not the old
``Spell.desc`` blurbs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pygame

from py_exodus.constants import Spell
from py_exodus.screens.base import BaseScreen
from py_exodus.ui.text_log import (
    EGA_BLACK,
    EGA_BRIGHT_CYAN,
    EGA_BRIGHT_GREEN,
    EGA_BRIGHT_MAGENTA,
    EGA_BRIGHT_RED,
    EGA_DARK_GRAY,
    EGA_LIGHT_GRAY,
    EGA_WHITE,
    EGA_YELLOW,
    get_hud_font,
)


@dataclass(frozen=True)
class QuickCommand:
    """One row of the commands card.

    ``where`` holds the places the key does its work: S Sosaria (Ambrosia
    too, except Q, which saves on Sosaria only), T town or castle, D
    dungeon, C combat.
    """

    key: str
    name: str
    desc: str
    where: str


#: Verified against OverworldScreen.handle_event, TownScreen.handle_event,
#: DungeonScreen._dispatch_command (A B E F L Q S T U X are "NOT A DNG
#: CMD!") and CombatScreen._on_combat_key (A C N R W, Z, Space/P, Tab/F2).
COMMANDS: tuple[QuickCommand, ...] = (
    QuickCommand("A", "Attack", "fight in a direction", "STC"),
    QuickCommand("B", "Board", "mount a horse, board a ship", "ST"),
    QuickCommand("C", "Cast", "cast a spell", "STDC"),
    QuickCommand("D", "Descend", "down a ladder", "D"),
    QuickCommand("E", "Enter", "a town, dungeon or shrine", "S"),
    QuickCommand("F", "Fire", "the ship's cannons", "S"),
    QuickCommand("G", "Get chest", "open a chest", "STD"),
    QuickCommand("H", "Hand", "give food, gold or items", "STD"),
    QuickCommand("I", "Ignite", "light a torch", "D"),
    QuickCommand("J", "Join gold", "pool gold in one member", "STD"),
    QuickCommand("K", "Klimb", "up a ladder", "D"),
    QuickCommand("L", "Look", "name what lies that way", "ST"),
    QuickCommand("M", "Modify order", "swap two members", "STD"),
    QuickCommand("N", "Negate time", "stop time (powder)", "STDC"),
    QuickCommand("O", "Other", "type a command word", "STD"),
    QuickCommand("P", "Peer", "view the map (gem)", "STD"),
    QuickCommand("Q", "Quit & save", "save (Sosaria only)", "S"),
    QuickCommand("R", "Ready", "ready a weapon", "STDC"),
    QuickCommand("S", "Steal", "from behind a counter", "T"),
    QuickCommand("T", "Transact", "talk, buy, sell", "T"),
    QuickCommand("U", "Unlock", "open a door (key)", "T"),
    QuickCommand("V", "Volume", "sound on or off", "STD"),
    QuickCommand("W", "Wear", "put on armour", "STDC"),
    QuickCommand("X", "X-it", "leave a horse or ship", "ST"),
    QuickCommand("Y", "Yell", "shout a word", "STD"),
    QuickCommand("Z", "Ztats", "a member's stats", "STDC"),
    QuickCommand("Spc", "Pass", "let a turn go by (P in a fight)", "STDC"),
    QuickCommand("Tab", "Auto-combat", "fight for me (or F2)", "C"),
)

#: Badge letter, legend word and colour for each place.
PLACES: tuple[tuple[str, str, tuple[int, int, int]], ...] = (
    ("S", "Sosaria", EGA_BRIGHT_GREEN),
    ("T", "Town", EGA_BRIGHT_CYAN),
    ("D", "Dungeon", EGA_BRIGHT_MAGENTA),
    ("C", "Combat", EGA_BRIGHT_RED),
)

#: One line per spell, from the rules as combat/magic.py works them.
SPELL_EFFECTS: dict[Spell, str] = {
    Spell.REPOND: "Kills orcs 3 in 4; half the time, one try a fight",
    Spell.MITTAR: "Bolt for 16-31 or 48-56 damage",
    Spell.LORUM: "Light for 10 turns, unless a longer light is lit",
    Spell.DOR_ACRON: "Down one level (not from the lowest)",
    Spell.SUR_ACRON: "Up one level; from the top, out",
    Spell.FULGAR: "Bolt for 75 damage",
    Spell.DAG_ACRON: "Party to random grass; never aboard ship",
    Spell.MENTAR: "Bolt for damage equal to the caster's INT",
    Spell.DAG_LORUM: "Long light, at least 250 turns",
    Spell.FAL_DIVI: "Cast a cleric spell, paying for both",
    Spell.NOXUM: "75 damage to each foe, 3 times in 4",
    Spell.DECORP: "Bolt that kills (255 damage)",
    Spell.ALTAIR: "Holds the monsters for 20 rounds",
    Spell.DAG_MENTAR: "Twice the caster's INT to each foe, 3 in 4",
    Spell.NECORP: "Every monster drops to 5 HP",
    Spell.UNSPEAKABLE: "Kills each foe, 3 times in 4",
    Spell.PONTORI: "Kills skeletons 3 in 4; half the time, one try a fight",
    Spell.APPAR_UNEM: "Opens a chest untrapped; fails 1 time in 4",
    Spell.SANCTU: "Heals one member 10-30 HP",
    Spell.LUMINAE: "Light for 10 turns, unless a longer light is lit",
    Spell.REC_SU: "Up one level; from the top, out",
    Spell.REC_DU: "Down one level (not from the lowest)",
    Spell.LIB_REC: "To a random spot on this level",
    Spell.ALCORT: "Cures poison",
    Spell.SEQUITU: "Out of the dungeon",
    Spell.SOMINAE: "Long light, at least 250 turns",
    Spell.SANCTU_MANI: "Heals one member 20-100 HP",
    Spell.VIEDA: "Shows the whole map, as a gem does",
    Spell.EXCUUN: "Bolt that kills (255 damage)",
    Spell.SURMANDUM: "Raises the dead; 1 in 4 turn to ashes",
    Spell.ZXKUQYB: "Kills each foe, 3 times in 4",
    Spell.ANJU_SERMANI: "Recalls from ashes; the caster loses 5 WIS",
}

#: Location-mask bits in player words (constants.MapType.mask). Ambrosia
#: is a city map, so for spells it counts as a town.
_SPELL_PLACES: tuple[tuple[int, str], ...] = (
    (0x01, "Sosaria"),
    (0x02, "combat"),
    (0x04, "town"),
    (0x08, "dungeon"),
)


def spell_where(spell: Spell) -> str:
    """Where ``spell`` may be cast, from its location mask."""
    have = [label for bit, label in _SPELL_PLACES if spell.location_mask & bit]
    if len(have) == len(_SPELL_PLACES):
        return "anywhere"
    if len(have) == len(_SPELL_PLACES) - 1 and "combat" not in have:
        return "not in combat"
    return ", ".join(have)


def spell_display_name(spell: Spell) -> str:
    if spell is Spell.ZXKUQYB:
        return "ZXKUQYB"
    return spell.name.replace("_", " ").title()


CARDS = ("commands", "wizard", "cleric")
_TAB_LABELS = {"commands": "Commands", "wizard": "Wizard spells", "cleric": "Cleric spells"}
COMMANDS_HINT = "F3 closes · F4 spells · any key closes · game paused"
SPELLS_HINT = (
    "F4 closes · Tab Wizard/Cleric · F3 commands · any key closes · game paused"
)

#: Keys that never close the card (held for a chord, or lock keys).
_IGNORED_KEYS = frozenset((
    pygame.K_LSHIFT, pygame.K_RSHIFT, pygame.K_LCTRL, pygame.K_RCTRL,
    pygame.K_LALT, pygame.K_RALT, pygame.K_LMETA, pygame.K_RMETA,
    pygame.K_LGUI, pygame.K_RGUI, pygame.K_CAPSLOCK, pygame.K_NUMLOCK,
    pygame.K_SCROLLOCK, pygame.K_MODE,
))

_FRAME_BG = (24, 20, 16)
_FRAME_EDGE = (200, 160, 40)
_RULE = (90, 80, 70)
_TAB_FILL = (70, 55, 20)
_BADGE_EMPTY = (60, 60, 60)

# Layout in 960x600 units; ``_u`` scales them to the surface (x1/3 at 320).
_COL_W = 444
_CMD_ROWS = 14
_CMD_TOP, _CMD_STEP = 82, 32
_CMD_NAME_X, _CMD_DESC_X, _CMD_BADGE_X = 44, 166, 356
_SPELL_ROWS = 8
_SPELL_TOP, _SPELL_STEP = 84, 56
_SPELL_NAME_X, _SPELL_MP_X, _SPELL_WHERE_X = 34, 226, 296


def _u(v: float, scale: int) -> int:
    return int(round(v * scale / 3))


def _font(size: int, scale: int) -> pygame.font.Font:
    return get_hud_font(max(5, _u(size, scale)))


def command_row_overflows(scale: int) -> list[str]:
    """Rows whose name or description runs into the next field."""
    fb, fs = _font(19, scale), _font(16, scale)
    gap = _u(6, scale)
    bad = []
    for cmd in COMMANDS:
        if fb.size(cmd.name)[0] > _u(_CMD_DESC_X - _CMD_NAME_X, scale) - gap:
            bad.append(cmd.key)
        elif fs.size(cmd.desc)[0] > _u(_CMD_BADGE_X - _CMD_DESC_X, scale) - gap:
            bad.append(cmd.key)
    return bad


def spell_row_overflows(scale: int) -> list[str]:
    fb, fs = _font(19, scale), _font(16, scale)
    gap = _u(6, scale)
    bad = []
    for sp in Spell:
        if fb.size(spell_display_name(sp))[0] > _u(_SPELL_MP_X - _SPELL_NAME_X, scale) - gap:
            bad.append(sp.name)
        elif fs.size(spell_where(sp))[0] > _u(_COL_W - _SPELL_WHERE_X, scale) - gap:
            bad.append(sp.name)
        elif fs.size(SPELL_EFFECTS[sp])[0] > _u(_COL_W - _SPELL_NAME_X, scale) - gap:
            bad.append(sp.name)
    return bad


class QuickRefScreen(BaseScreen):
    """The commands card or one of the two spell cards, over the game."""

    def __init__(
        self,
        card: str = "commands",
        return_screen: BaseScreen | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(return_screen=return_screen, **kwargs)
        if card not in CARDS:
            raise ValueError(card)
        self.card = card
        self._backdrop: pygame.Surface | None = None

    # --- input --------------------------------------------------------------

    def _last_spell_card(self) -> str:
        card = getattr(self.manager, "quickref_spell_card", "wizard")
        return card if card in ("wizard", "cleric") else "wizard"

    def _show(self, card: str) -> None:
        self.card = card
        if card != "commands" and self.manager is not None:
            self.manager.quickref_spell_card = card

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN or event.key in _IGNORED_KEYS:
            return
        if event.key == pygame.K_F3:
            if self.card == "commands":
                self.exit_screen()
            else:
                self._show("commands")
        elif event.key == pygame.K_F4:
            if self.card == "commands":
                self._show(self._last_spell_card())
            else:
                self.exit_screen()
        elif event.key == pygame.K_TAB and self.card != "commands":
            self._show("cleric" if self.card == "wizard" else "wizard")
        else:
            self.exit_screen()

    # --- drawing ------------------------------------------------------------

    def _draw_backdrop(self, surface: pygame.Surface) -> None:
        """The paused game, dimmed. Drawn once: nothing beneath moves."""
        size = surface.get_size()
        if self._backdrop is None or self._backdrop.get_size() != size:
            surface.fill(EGA_BLACK)
            if self.return_screen is not None:
                self.return_screen.render(surface)
            dim = pygame.Surface(size, pygame.SRCALPHA)
            dim.fill((0, 0, 0, 170))
            surface.blit(dim, (0, 0))
            self._backdrop = surface.copy()
        else:
            surface.blit(self._backdrop, (0, 0))

    def render(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        scale = 3 if width >= 640 else 1
        self._draw_backdrop(surface)

        frame = pygame.Rect(_u(24, scale), _u(20, scale), width - 2 * _u(24, scale), height - 2 * _u(20, scale))
        pygame.draw.rect(surface, _FRAME_BG, frame)
        pygame.draw.rect(surface, _FRAME_EDGE, frame, max(1, _u(4, scale)))

        fh = _font(26, scale)
        x = _u(44, scale)
        for card in CARDS:
            label = fh.render(_TAB_LABELS[card], True, EGA_YELLOW if card == self.card else EGA_DARK_GRAY)
            if card == self.card:
                pygame.draw.rect(
                    surface, _TAB_FILL,
                    (x - _u(10, scale), _u(28, scale), label.get_width() + _u(20, scale), _u(38, scale)),
                )
            surface.blit(label, (x, _u(30, scale)))
            x += label.get_width() + _u(40, scale)
        pygame.draw.line(
            surface, _RULE, (_u(40, scale), _u(72, scale)), (width - _u(40, scale), _u(72, scale)),
        )

        if self.card == "commands":
            self._render_commands(surface, scale)
            hint = COMMANDS_HINT
        else:
            self._render_spells(surface, scale)
            hint = SPELLS_HINT
        fs = _font(16, scale)
        hint_surf = fs.render(hint, True, EGA_BRIGHT_GREEN)
        surface.blit(hint_surf, (width - _u(48, scale) - hint_surf.get_width(), height - _u(50, scale)))

    def _badge(self, surface, scale, code, colour, x, y, filled) -> None:
        rect = pygame.Rect(x, y, _u(16, scale), _u(16, scale))
        radius = _u(3, scale)
        if filled:
            pygame.draw.rect(surface, colour, rect, border_radius=radius)
            fx = _font(14, scale)
            t = fx.render(code, True, EGA_BLACK)
            surface.blit(t, (rect.centerx - t.get_width() // 2, rect.centery - t.get_height() // 2))
        else:
            pygame.draw.rect(surface, _BADGE_EMPTY, rect, 1, border_radius=radius)

    def _render_commands(self, surface: pygame.Surface, scale: int) -> None:
        fb, fs = _font(19, scale), _font(16, scale)
        for i, cmd in enumerate(COMMANDS):
            col, row = divmod(i, _CMD_ROWS)
            x = _u(48 + col * _COL_W, scale)
            y = _u(_CMD_TOP + row * _CMD_STEP, scale)
            surface.blit(fb.render(cmd.key, True, EGA_BRIGHT_CYAN), (x, y))
            surface.blit(fb.render(cmd.name, True, EGA_WHITE), (x + _u(_CMD_NAME_X, scale), y))
            surface.blit(fs.render(cmd.desc, True, EGA_LIGHT_GRAY), (x + _u(_CMD_DESC_X, scale), y + _u(2, scale)))
            bx = x + _u(_CMD_BADGE_X, scale)
            for code, _label, colour in PLACES:
                self._badge(surface, scale, code, colour, bx, y + _u(6, scale), code in cmd.where)
                bx += _u(20, scale)

        lx = _u(48, scale)
        ly = surface.get_height() - _u(52, scale)
        for code, label, colour in PLACES:
            self._badge(surface, scale, code, colour, lx, ly + _u(4, scale), True)
            t = fs.render(label, True, EGA_LIGHT_GRAY)
            surface.blit(t, (lx + _u(22, scale), ly + _u(2, scale)))
            lx += _u(40, scale) + t.get_width()

    def _render_spells(self, surface: pygame.Surface, scale: int) -> None:
        fh, fb, fs = _font(26, scale), _font(19, scale), _font(16, scale)
        spells = [sp for sp in Spell if sp.spell_type == self.card]
        for i, sp in enumerate(spells):
            col, row = divmod(i, _SPELL_ROWS)
            x = _u(48 + col * _COL_W, scale)
            y = _u(_SPELL_TOP + row * _SPELL_STEP, scale)
            surface.blit(fh.render(sp.code, True, EGA_BRIGHT_CYAN), (x, y))
            surface.blit(fb.render(spell_display_name(sp), True, EGA_WHITE), (x + _u(_SPELL_NAME_X, scale), y))
            surface.blit(fs.render(f"{sp.mp_cost} MP", True, EGA_YELLOW), (x + _u(_SPELL_MP_X, scale), y + _u(2, scale)))
            surface.blit(fs.render(spell_where(sp), True, (130, 130, 130)), (x + _u(_SPELL_WHERE_X, scale), y + _u(2, scale)))
            surface.blit(
                fs.render(SPELL_EFFECTS[sp], True, EGA_LIGHT_GRAY),
                (x + _u(_SPELL_NAME_X, scale), y + _u(26, scale)),
            )
