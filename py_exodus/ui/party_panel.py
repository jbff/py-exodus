"""The right-hand party panel (approved mockup, 2026-11-22).

Framed member cards on top (name, race/class/sex/level in words, HP/MP bars,
food, gold, stats, experience, readied weapon and worn armor, a status edge
and tag), then the party's supplies, the quest chips (marks, cards, exotics)
and location / turn / autoplay (with its goal) / autocombat.
"""
from __future__ import annotations

import pygame

from py_exodus.constants import ArmorType, Status, WeaponType
from py_exodus.ui.text_log import get_hud_font

BOLD_FONT = "BarlowSemiCondensed-SemiBold.ttf"

INK = (216, 216, 216)
WHITE = (255, 255, 255)
DIM = (170, 170, 170)
FAINT = (102, 102, 102)
FRAME = (58, 58, 58)
SECTION = (51, 51, 51)
HEADER = (125, 143, 160)
WHO = (143, 176, 200)
GEAR = (208, 168, 96)
GOLDEN = (255, 216, 74)
ACTIVE_FRAME = (107, 90, 26)
HP_RED = (232, 48, 48)
MP_BLUE = (32, 192, 224)
BAR_BG = (58, 58, 58)
CYAN = (95, 224, 255)
ON_GREEN = (125, 255, 125)
OFF = (119, 119, 119)

# Card edge and tag per status (spec item 5: status-colored edge).
STATUS_LOOK = {
    Status.POISONED: ((63, 212, 63), "POISONED", (31, 111, 31), (191, 255, 191)),
    Status.DEAD: ((200, 48, 48), "DEAD", (110, 24, 24), (255, 200, 200)),
    Status.ASH: ((150, 150, 150), "ASHES", (70, 70, 70), (230, 230, 230)),
}

MARKS = (("Kings", 0), ("Fire", 1), ("Snake", 2), ("Force", 3))
CARDS = (("Love", 3), ("Sol", 1), ("Moons", 2), ("Death", 0))
MARK_ON, CARD_ON, EXOTIC_ON = (224, 176, 64), (127, 200, 255), (200, 139, 255)

GOAL_LABELS = {
    "setup_party": "Form the party",
    "buy_food": "Buy food",
    "resurrect_dead": "Raise the dead",
    "cure_poison": "Cure poison",
    "outfit_britain": "Outfit in Britain",
    "grind_and_level": "Level up",
    "buy_gems": "Buy gems",
    "buy_torches": "Buy torches",
    "get_mark_kings": "Mark of Kings",
    "buy_keys": "Buy keys",
    "sail_whirlpool": "Sail the whirlpool",
    "ambrosia_cards_shrines": "Ambrosia: cards, shrines",
    "exit_ambrosia": "Leave Ambrosia",
    "get_remaining_marks": "The other Marks",
    "dig_exotics": "Dig the exotics",
    "conquer_exodus": "Conquer Exodus",
    "done": "Done",
}


def _fmt(n: int) -> str:
    return f"{n:,}"


def _title(enum_value) -> str:
    return str(getattr(enum_value, "name", enum_value) or "?").replace("_", " ").title()


def sky_wind_text(sky: dict) -> str | None:
    """The wind words after the moons; None where LairWare hides the wind
    (dungeons, combat)."""
    if not sky.get("show_wind", True):
        return None
    wind = sky.get("wind")
    return "Wind CALM" if wind is None else f"Wind {wind.name}"


class _Flow:
    """Left-to-right runs of text and widgets that wrap inside a width."""

    def __init__(self, surface, x, y, width, line_h, gap):
        self.s, self.x0, self.x, self.y = surface, x, x, y
        self.right, self.line_h, self.gap = x + width, line_h, gap

    def _place(self, w):
        if self.x > self.x0 and self.x + w > self.right:
            self.x, self.y = self.x0, self.y + self.line_h
        pos = (self.x, self.y)
        self.x += w + self.gap
        return pos

    def text(self, font, text, color, tight=False):
        img = font.render(text, True, color)
        x, y = self._place(img.get_width())
        self.s.blit(img, (x, y + (self.line_h - img.get_height()) // 2))
        if tight:
            self.x -= self.gap // 2
        return img.get_width()

    def bar(self, frac, color, w=50, h=9):
        x, y = self._place(w)
        top = y + (self.line_h - h) // 2
        pygame.draw.rect(self.s, BAR_BG, (x, top, w, h), border_radius=2)
        fill = int(round(w * max(0.0, min(1.0, frac))))
        if fill:
            pygame.draw.rect(self.s, color, (x, top, fill, h), border_radius=2)

    def chip(self, font, text, lit_color):
        img = font.render(text, True, (0, 0, 0) if lit_color else FAINT)
        w = img.get_width() + 12
        x, y = self._place(w)
        r = pygame.Rect(x, y + 1, w, self.line_h - 2)
        if lit_color:
            pygame.draw.rect(self.s, lit_color, r, border_radius=r.height // 2)
        else:
            pygame.draw.rect(self.s, (68, 68, 68), r, width=1, border_radius=r.height // 2)
        self.s.blit(img, (x + 6, r.y + (r.height - img.get_height()) // 2))

    def moon(self, phase, radius):
        from py_exodus.screens.overworld import draw_moon_glyph

        size = 2 * radius + 3
        x, y = self._place(size)
        draw_moon_glyph(self.s, x + size // 2, y + self.line_h // 2, radius, phase)

    def newline(self):
        self.x, self.y = self.x0, self.y + self.line_h

    def bottom(self):
        return self.y + self.line_h if self.x > self.x0 else self.y


class PartyPanel:
    """Draws the panel into a rect of at least 240 pixels' width."""

    def __init__(self, names: tuple[dict, dict] = ({}, {}), font=None):
        self.weapon_names, self.armor_names = names
        self.font = font  # one font for everything (tests)

    def fonts(self, width: int):
        if self.font is not None:
            return (self.font,) * 4
        k = width / 432.0
        size = lambda px: max(10, int(round(px * k)))  # noqa: E731
        return (
            get_hud_font(size(19), BOLD_FONT),  # name
            get_hud_font(size(14)),  # body
            get_hud_font(size(12), BOLD_FONT),  # section header, tags
            get_hud_font(size(14), BOLD_FONT),  # values
        )

    def render(self, surface, party, rect, *, autoplay=False, auto_combat=False,
               step_interval=None, location_text=None, goal=None, sky=None) -> int:
        f_name, f_body, f_small, f_bold = self.fonts(rect.width)
        pad = max(4, rect.width // 72)
        line_h = f_body.get_linesize() + 5
        y = rect.y + pad
        inner = pygame.Rect(rect.x + pad, 0, rect.width - 2 * pad, 0)

        for i, m in enumerate(party.members):
            y = self._member(surface, m, i == party.active_member_index, inner, y,
                             f_name, f_body, f_small, line_h) + 6

        # Party supplies
        y = self._section(surface, inner, y, "PARTY", f_small, lambda fl: self._supplies(
            fl, party, f_body, f_bold), line_h)
        # Quest
        y = self._section(surface, inner, y, "QUEST", f_small, lambda fl: self._quest(
            fl, party, f_body, f_small), line_h + 2)
        # Where / turn / autoplay
        y = self._section(surface, inner, y, None, f_small, lambda fl: self._status(
            fl, party, f_body, f_bold, autoplay, auto_combat, step_interval,
            location_text, goal, sky), line_h)
        return y

    # -- pieces ---------------------------------------------------------

    def _member(self, s, m, active, inner, y, f_name, f_body, f_small, line_h):
        look = STATUS_LOOK.get(m.status)
        edge = GOLDEN if active else (look[0] if look else (85, 85, 85))
        frame = ACTIVE_FRAME if active else FRAME
        x = inner.x + 4 + 7
        w = inner.width - 4 - 14
        top = y
        y += 5
        # line 1: name (+ tag) ... who
        name_img = f_name.render(m.name.upper(), True, GOLDEN if active else WHITE)
        s.blit(name_img, (x, y))
        nx = x + name_img.get_width() + 6
        if look:
            tag = f_small.render(look[1], True, look[3])
            tr = pygame.Rect(nx, y + (name_img.get_height() - tag.get_height()) // 2,
                             tag.get_width() + 8, tag.get_height())
            pygame.draw.rect(s, look[2], tr, border_radius=2)
            s.blit(tag, (nx + 4, tr.y))
        sex = getattr(getattr(m, "sex", None), "value", getattr(m, "sex", ""))
        who = f"{_title(m.race)} {_title(m.profession)} · {sex} · Lv {m.level}"
        who_img = f_body.render(who, True, WHO)
        s.blit(who_img, (x + w - who_img.get_width(), y + name_img.get_height() - who_img.get_height()))
        y += name_img.get_height()
        # line 2: HP, MP, food, gold
        fl = _Flow(s, x, y, w, line_h, 9)
        fl.text(f_body, "HP", INK, tight=True)
        fl.bar(m.hp / m.max_hp if m.max_hp else 0, HP_RED)
        fl.text(f_body, f"{_fmt(m.hp)}/{_fmt(m.max_hp)}", INK)
        if m.max_mp > 0:
            fl.text(f_body, "MP", INK, tight=True)
            fl.bar(m.mp / m.max_mp, MP_BLUE)
            fl.text(f_body, f"{m.mp}/{m.max_mp}", INK)
        else:
            fl.text(f_body, "MP —", INK)
        fl.text(f_body, f"Food {_fmt(m.food)}", INK)
        fl.text(f_body, f"Gold {_fmt(m.gold)}", INK)
        fl.newline()
        # line 3: stats, experience, gear
        fl.text(f_body, f"S {m.str} D {m.dex} I {m.int} W {m.wis}", DIM)
        fl.text(f_body, f"XP {_fmt(m.exp)}", DIM)
        fl.text(f_body, self._gear(m), GEAR)
        y = fl.bottom() + 4
        box = pygame.Rect(inner.x, top, inner.width, y - top)
        pygame.draw.rect(s, frame, box, width=1, border_radius=2)
        pygame.draw.rect(s, edge, (inner.x, top, 4, box.height),
                         border_top_left_radius=2, border_bottom_left_radius=2)
        return y

    def _gear(self, m) -> str:
        def name(kind, names):
            key = getattr(kind, "name", "NONE")
            return "Exotic" if key == "EXOTIC" else names.get(key, _title(kind))
        return f"{name(m.weapon, self.weapon_names)} · {name(m.armor, self.armor_names)}"

    def _section(self, s, inner, y, title, f_small, body, line_h):
        top = y
        x, w = inner.x + 7, inner.width - 14
        y += 5
        if title:
            img = f_small.render(title, True, HEADER)
            s.blit(img, (x, y))
            y += img.get_height()
        fl = _Flow(s, x, y, w, line_h, 12)
        body(fl)
        y = fl.bottom() + 5
        pygame.draw.rect(s, SECTION, (inner.x, top, inner.width, y - top), width=1, border_radius=2)
        return y + 6

    @staticmethod
    def _kv(fl, f_body, f_bold, label, value):
        fl.text(f_body, label, INK, tight=True)
        fl.text(f_bold, value, WHITE)

    def _supplies(self, fl, party, f_body, f_bold):
        tot = lambda a: sum(getattr(m, a) for m in party.members)  # noqa: E731
        for label, value in (("Food", party.food), ("Gold", party.gold), ("Keys", tot("keys")),
                             ("Gems", tot("gems")), ("Torches", tot("torches")),
                             ("Powders", tot("powder"))):
            self._kv(fl, f_body, f_bold, label, _fmt(value))
        if party.torch_duration > 0:
            self._kv(fl, f_body, f_bold, "Torchlight", str(party.torch_duration))

    def _quest(self, fl, party, f_body, f_small):
        members = party.members
        fl.text(f_body, "Marks", INK)
        for label, i in MARKS:
            # Lit only when the quest is done: every member holds the mark
            # (the force fields and the castle want it on each one).
            fl.chip(f_body, label, MARK_ON if members and all(m.marks[i] for m in members) else None)
        fl.newline()
        fl.text(f_body, "Cards", INK)
        for label, i in CARDS:
            fl.chip(f_body, label, CARD_ON if any(m.cards[i] for m in members) else None)
        fl.newline()
        ew = sum(1 for m in members if m.weapon == WeaponType.EXOTIC
                 or m.weapons.get(WeaponType.EXOTIC, 0) > 0)
        ea = sum(1 for m in members if m.armor == ArmorType.EXOTIC
                 or m.armors.get(ArmorType.EXOTIC, 0) > 0)
        n = len(members)
        # Like the marks: lit once every member has one, no count.
        fl.text(f_body, "Exotics", INK)
        fl.chip(f_body, "Weapons", EXOTIC_ON if n and ew >= n else None)
        fl.chip(f_body, "Armor", EXOTIC_ON if n and ea >= n else None)

    def _status(self, fl, party, f_body, f_bold, autoplay, auto_combat, step_interval,
                location_text, goal, sky=None):
        if location_text:
            fl.text(f_body, location_text, CYAN)
        self._kv(fl, f_body, f_bold, "Turn", _fmt(party.moves))
        fl.newline()
        if sky is not None:
            # Moons first (Trammel, Felucca) so they never move with the
            # wind's length, then the wind where it is shown.
            fl.text(f_body, "Moons", INK)
            radius = max(3, fl.line_h // 3)
            fl.moon(sky["trammel"], radius)
            fl.moon(sky["felucca"], radius)
            fl.x += fl.gap
            wind = sky_wind_text(sky)
            if wind:
                fl.text(f_body, wind, INK)
            aura = sky.get("aura")
            if aura is not None and getattr(aura, "name", "NONE") != "NONE":
                fl.chip(f_body, aura.name.title(), GOLDEN)
            fl.newline()
        fl.text(f_body, "Autoplay", INK, tight=True)
        if autoplay:
            speed = f" ({step_interval:.2f}s)" if step_interval is not None else ""
            fl.text(f_bold, f"ON{speed}", ON_GREEN)
            if goal:
                fl.text(f_body, GOAL_LABELS.get(goal, goal), GOLDEN)
        else:
            fl.text(f_body, "OFF", OFF)
        on = bool(autoplay or auto_combat)
        fl.text(f_body, "Autocombat", INK, tight=True)
        fl.text(f_bold if on else f_body, "ON" if on else "OFF", ON_GREEN if on else OFF)
