"""The roster screen's look (approved mockup "A", 2026-11-26).

THE PARTY: up to four party cards along the top (a dashed "Open place"
card for a free place), the roster as one list of 20 rows that scrolls with
the selection, a detail card for the chosen character (sprite, stats as bars
with the race maximum marked, readied and worn gear, Marks) and the real
keys as chips along the bottom.

A NEW ADVENTURER: the five creation steps (name, sex, race, class, stats)
beside a preview card that fills in as the choices are made.

At 960x600 the full layout is drawn (any width of 640 or more is drawn at
960x600 and scaled); below that a plain text layout is used, with no
detail card. Only drawing lives here: the screen's rules stay in
``py_exodus.screens.roster_screen``.
"""
from __future__ import annotations

from typing import Any

import pygame

from py_exodus.constants import ArmorType, Profession, Race, Sex, Status, WeaponType
from py_exodus.ui.text_log import get_hud_font

BOLD_FONT = "BarlowSemiCondensed-SemiBold.ttf"

BG = (14, 12, 10)
PANEL = (28, 24, 20)
LINE = (70, 62, 52)
GOLD = (255, 216, 74)
FG = (220, 214, 204)
DIM = (130, 122, 110)
FAINT = (90, 84, 76)
EMPTY_INK = (70, 64, 56)
CYAN = (111, 255, 255)
GREEN = (85, 255, 85)
RED = (255, 85, 85)
EDGE = (154, 90, 18)
SEL = (64, 48, 20)
BAR = (110, 200, 255)
BAR_BG = (40, 36, 30)
BLOCK_OFF = (44, 40, 34)
CHIP_INK = (20, 16, 10)

TITLE_MAIN = "THE PARTY"
SUBTITLE_MAIN = "Choose up to four to set out. The rest wait at the inn."
SUBTITLE_IN_USE = "A party is in use. X disperses it; Esc goes back to resume it."
TITLE_CREATE = "A NEW ADVENTURER"

# The roster screen's real keys (RosterScreen.handle_event), in chip order.
ROSTER_KEYS = (
    ("A", "add"),
    ("R", "remove"),
    ("C", "create"),
    ("D", "delete"),
    ("X", "disperse"),
    ("P", "save"),
    ("Tab", "party/roster"),
    ("Enter", "set out"),
    ("Esc", "back"),
)

VISIBLE_ROWS = 10
CREATION_STEPS = ("Name", "Sex", "Race", "Class", "Stats")
STAT_LABELS = ("Strength", "Dexterity", "Intelligence", "Wisdom")
STAT_SHORT = ("STR", "DEX", "INT", "WIS")
# What each stat does (combat/resolver.py: STR the weapon damage, DEX the
# to-hit roll; Character.mp_max_parts: INT and WIS the MP max).
STAT_WHAT = ("weapon damage", "to hit", "Wizard magic", "Cleric magic")
TAG_LOOK = {Status.DEAD: ("dead", RED), Status.ASH: ("ashes", (190, 190, 190)),
            Status.POISONED: ("poisoned", GREEN)}
MARK_NAMES = ("Kings", "Fire", "Snake", "Force")
SEX_WORD = {"M": "Male", "F": "Female", "O": "Other"}


# -- what the screen shows (pure, tested) -----------------------------------


def scroll_offset(selected: int, offset: int, rows: int = VISIBLE_ROWS, total: int = 20) -> int:
    """The first row shown so that ``selected`` is in the window of
    ``rows`` rows, moving the window as little as possible."""
    offset = max(0, min(offset, total - rows))
    if selected < offset:
        offset = selected
    elif selected >= offset + rows:
        offset = selected - rows + 1
    return max(0, min(offset, total - rows))


def scroll_hints(offset: int, count: int, rows: int = VISIBLE_ROWS) -> tuple[str | None, str | None]:
    """(above, below): a hint when characters lie above or below the rows
    shown, None when none do."""
    above = None
    if offset == 1:
        above = "Row 1 above (Up)"
    elif offset > 1:
        above = f"Rows 1-{offset} above (Up)"
    below = None
    if count == offset + rows + 1:
        below = f"Row {count} below (Down)"
    elif count > offset + rows:
        below = f"Rows {offset + rows + 1}-{count} below (Down)"
    return above, below


def status_tag(char: Any) -> tuple[str, tuple[int, int, int]] | None:
    """("dead" | "ashes" | "poisoned", colour), or None for a good one."""
    return TAG_LOOK.get(getattr(char, "status", None))


def words(enum_value: Any) -> str:
    return str(getattr(enum_value, "name", enum_value) or "?").replace("_", " ").title()


def sex_word(sex: Any) -> str:
    return SEX_WORD.get(str(getattr(sex, "value", sex))[:1], "")


def best_gear(prof: Profession) -> tuple[WeaponType, ArmorType]:
    """The best weapon and armour the class may ready (the Exotics aside)."""
    from py_exodus.autoplay.equipment import PROFESSION_ARMORS, PROFESSION_WEAPONS

    def best(kinds, enum_cls):
        order = list(enum_cls)
        return max((t for t in kinds if t.name != "EXOTIC"), key=order.index)

    return best(PROFESSION_WEAPONS[prof], WeaponType), best(PROFESSION_ARMORS[prof], ArmorType)


def gear_name(kind: Any, names: dict) -> str:
    key = getattr(kind, "name", "NONE")
    if key == "EXOTIC":
        return "Exotic"
    return names.get(key, words(kind))


# -- drawing helpers -------------------------------------------------------


class Canvas:
    """Text that always fits its box: each draw shrinks the font, then
    trims with an ellipsis, until the text is inside ``box``. Every drawn
    text rect is logged with its box (tests check nothing overflows)."""

    def __init__(self, surface: pygame.Surface) -> None:
        self.s = surface
        self.log: list[tuple[str, pygame.Rect, pygame.Rect]] = []
        self.cut: list[str] = []  # texts drawn shortened with "…"

    @staticmethod
    def font(size: int, bold: bool = False) -> pygame.font.Font:
        return get_hud_font(size, BOLD_FONT if bold else None)

    def text(self, t: str, x: int, y: int, size: int, col, box: pygame.Rect | None = None,
             align: str = "left", bold: bool = False, min_size: int | None = None) -> pygame.Rect:
        if box is None:
            box = self.s.get_rect()
        floor = min_size if min_size is not None else max(8, size - 4)
        sz = size
        img = self.font(sz, bold).render(t, True, col)
        while img.get_width() > box.width and sz > floor:
            sz -= 1
            img = self.font(sz, bold).render(t, True, col)
        cut = t
        while img.get_width() > box.width and cut:
            cut = cut[:-1]
            img = self.font(sz, bold).render(cut.rstrip() + "…", True, col)
        if align == "right":
            x -= img.get_width()
        elif align == "center":
            x -= img.get_width() // 2
        if cut != t:
            self.cut.append(t)
        x = max(box.x, min(x, box.right - img.get_width()))
        r = img.get_rect(topleft=(x, y))
        self.s.blit(img, r)
        self.log.append((t, r, box))
        return r

    def chip(self, x: int, y: int, label: str, on: bool = True, col=GOLD, size: int = 15,
             box: pygame.Rect | None = None, h: int = 24) -> int:
        f = self.font(size)
        img = f.render(label, True, CHIP_INK if on else DIM)
        w = img.get_width() + 16
        r = pygame.Rect(x, y, w, h)
        if on:
            pygame.draw.rect(self.s, col, r, border_radius=h // 2)
        else:
            pygame.draw.rect(self.s, LINE, r, 1, border_radius=h // 2)
        tr = img.get_rect(center=r.center)
        self.s.blit(img, tr)
        self.log.append((label, r, box if box is not None else self.s.get_rect()))
        return w


def _dashed_rect(s: pygame.Surface, r: pygame.Rect, col, dash: int = 6, gap: int = 6) -> None:
    step = dash + gap
    for x in range(r.x, r.right, step):
        e = min(x + dash, r.right - 1)
        pygame.draw.line(s, col, (x, r.y), (e, r.y))
        pygame.draw.line(s, col, (x, r.bottom - 1), (e, r.bottom - 1))
    for y in range(r.y, r.bottom, step):
        e = min(y + dash, r.bottom - 1)
        pygame.draw.line(s, col, (r.x, y), (r.x, e))
        pygame.draw.line(s, col, (r.right - 1, y), (r.right - 1, e))


_SPRITES: dict[tuple[int, str, int], pygame.Surface | None] = {}


def sprite(asset_mgr: Any, prof: Any, size: int) -> pygame.Surface | None:
    """The class's map figure (``prof.tile``) at ``size`` pixels, or None."""
    if asset_mgr is None or prof is None:
        return None
    key = (id(asset_mgr), getattr(prof, "tile", ""), size)
    if key not in _SPRITES:
        try:
            img = asset_mgr.get_tile_surface(prof.tile)
            _SPRITES[key] = pygame.transform.scale(img, (size, size))
        except Exception:  # noqa: BLE001 - a missing tile leaves the space
            _SPRITES[key] = None
    return _SPRITES[key]


def _blit_sprite(s, asset_mgr, prof, size, x, y) -> None:
    img = sprite(asset_mgr, prof, size)
    if img is not None:
        s.blit(img, (x, y))


# -- THE PARTY -------------------------------------------------------------


def render_roster(surface: pygame.Surface, scr: Any, names: tuple[dict, dict] = ({}, {})) -> Canvas:
    """Draw the roster screen ``scr`` (a RosterScreen) into ``surface``."""
    w, h = surface.get_size()
    if w < 640:
        return _render_roster_small(surface, scr)
    if (w, h) == (960, 600):
        return _render_roster_full(surface, scr, names)
    big = pygame.Surface((960, 600))
    cv = _render_roster_full(big, scr, names)
    surface.blit(pygame.transform.smoothscale(big, (w, h)), (0, 0))
    return cv


def _message_line(scr: Any) -> tuple[str, bool]:
    """The newest log line, or the prompt waiting for an answer."""
    tl = scr.text_log
    if tl.is_waiting_for_input:
        return f"{tl.current_prompt} {tl.input_buffer}_", True
    return (tl.history[-1] if tl.history else ""), False


def _render_roster_full(s: pygame.Surface, scr: Any, names: tuple[dict, dict]) -> Canvas:
    s.fill(BG)
    cv = Canvas(s)
    am = scr.asset_mgr
    title = cv.text(TITLE_MAIN, 32, 18, 30, GOLD, bold=True)
    sub = SUBTITLE_IN_USE if scr.party_formed else SUBTITLE_MAIN
    cv.text(sub, title.right + 14, 26, 17, DIM, box=pygame.Rect(title.right + 14, 18, 928 - title.right - 14, 30))

    # Party cards along the top.
    members = scr.party.members
    for i in range(4):
        r = pygame.Rect(32 + i * 228, 64, 214, 96)
        if i < len(members):
            m = members[i]
            ch = getattr(m, "character", m)
            pygame.draw.rect(s, PANEL, r, border_radius=8)
            chosen = scr.focus_panel == "party" and scr.selected_party_idx == i
            pygame.draw.rect(s, GOLD if chosen else EDGE, r, 2 if not chosen else 3, border_radius=8)
            _blit_sprite(s, am, ch.profession, 48, r.x + 12, r.y + 24)
            inner = pygame.Rect(r.x + 68, r.y, r.width - 68 - 22, r.height)
            cv.text(ch.name.upper(), inner.x, r.y + 12, 22, GOLD, box=inner, bold=True, min_size=13)
            cv.text(f"{words(ch.race)} {words(ch.profession)}", inner.x, r.y + 40, 15, FG,
                    box=pygame.Rect(inner.x, r.y, r.right - 10 - inner.x, r.h))
            tag = status_tag(ch)
            info = f"Level {ch.level}  ·  {ch.hp} HP"
            if tag:
                cv.chip(inner.x, r.y + 62, tag[0], True, tag[1], 13, box=r, h=20)
            else:
                cv.text(info, inner.x, r.y + 62, 15, DIM, box=pygame.Rect(inner.x, r.y, r.right - 10 - inner.x, r.h))
            cv.text(str(i + 1), r.right - 14, r.y + 8, 15, DIM, align="right", box=r)
        else:
            pygame.draw.rect(s, PANEL, r, border_radius=8)
            chosen = scr.focus_panel == "party" and scr.selected_party_idx == i
            _dashed_rect(s, r, GOLD if chosen else LINE)
            cv.text("Open place", r.centerx, r.y + 30, 18, DIM, align="center", box=r.inflate(-8, 0))
            hint = "Disperse to change" if scr.party_formed else "A adds the chosen one"
            cv.text(hint, r.centerx, r.y + 54, 14, DIM, align="center", box=r.inflate(-8, 0))

    # The roster: one list of 20 rows, ten shown, scrolling with the selection.
    lx, ly = 32, 180
    count = len(scr.roster)
    cv.text(f"ROSTER  {count}/20", lx, ly, 14, DIM)
    offset = scr.roster_scroll_offset
    on_roster = scr.focus_panel == "roster"
    list_box = pygame.Rect(lx, ly + 24, 430, VISIBLE_ROWS * 34)
    for row in range(VISIBLE_ROWS):
        idx = offset + row
        y = ly + 24 + row * 34
        rr = pygame.Rect(lx, y, 430, 30)
        selected = idx == scr.selected_roster_idx and count > 0
        if selected:
            if on_roster:
                pygame.draw.rect(s, SEL, rr, border_radius=6)
            pygame.draw.rect(s, GOLD if on_roster else LINE, rr, 1, border_radius=6)
        cv.text(f"{idx + 1:>2}", lx + 26, y + 5, 15, DIM, align="right", box=list_box)
        if idx < count:
            ch = scr.roster[idx]
            _blit_sprite(s, am, ch.profession, 24, lx + 36, y + 3)
            cv.text(ch.name.upper(), lx + 70, y + 4, 18, GOLD if selected else FG,
                    box=pygame.Rect(lx + 70, y, 124, 30), min_size=13)
            cv.text(f"{words(ch.race)} {words(ch.profession)}", lx + 194, y + 6, 15, DIM,
                    box=pygame.Rect(lx + 194, y, 142, 30))
            cv.text(f"Lv {ch.level}", lx + 340, y + 6, 15, DIM, box=pygame.Rect(lx + 340, y, 36, 30))
            chip_x = lx + 378
            if scr._in_party(ch):
                chip_x += cv.chip(chip_x, y + 4, "party", True, CYAN, 13, h=22) + 4
            tag = status_tag(ch)
            if tag and chip_x < rr.right - 30:
                cv.chip(chip_x, y + 4, tag[0], True, tag[1], 13, h=22)
        else:
            cv.text("·  empty", lx + 40, y + 6, 15, EMPTY_INK)
    above, below = scroll_hints(offset, count)
    if above:
        cv.text(above, lx + 260, ly, 13, FAINT)
    if below:
        cv.text(below, lx + 40, ly + 24 + VISIBLE_ROWS * 34 + 2, 13, FAINT)

    # The detail card.
    card = pygame.Rect(486, 200, 442, 318)
    pygame.draw.rect(s, PANEL, card, border_radius=8)
    who = _detail_subject(scr)
    if who is None:
        msg = "No one here yet." if not scr.roster else "An open place."
        cv.text(msg, card.centerx, card.y + 120, 22, DIM, align="center", box=card.inflate(-24, 0))
        cv.text("C creates a new adventurer.", card.centerx, card.y + 156, 16, DIM,
                align="center", box=card.inflate(-24, 0))
    else:
        _detail_card(cv, scr, who, card, names)

    # The newest message, or the question waiting for an answer.
    msg, asking = _message_line(scr)
    if msg:
        cv.text(msg, card.x + 4, card.bottom + 10, 15, GOLD if asking else DIM,
                box=pygame.Rect(card.x, card.bottom + 6, card.width, 26))

    # The real keys, as chips.
    x = 32
    foot = pygame.Rect(0, 560, 960, 40)
    for k, lab in ROSTER_KEYS:
        x += cv.chip(x, 560, k, True, CYAN, 14, box=foot) + 6
        x += cv.text(lab, x, 562, 15, DIM, box=foot).width + 14
    return cv


def _detail_subject(scr: Any) -> Any:
    if scr.focus_panel == "party":
        members = scr.party.members
        if 0 <= scr.selected_party_idx < len(members):
            m = members[scr.selected_party_idx]
            return getattr(m, "character", m)
        return None
    if 0 <= scr.selected_roster_idx < len(scr.roster):
        return scr.roster[scr.selected_roster_idx]
    return None


def _detail_card(cv: Canvas, scr: Any, ch: Any, card: pygame.Rect, names: tuple[dict, dict]) -> None:
    s = cv.s
    dx, dy = card.x, card.y - 20
    _blit_sprite(s, scr.asset_mgr, ch.profession, 80, dx + 16, dy + 36)
    head = pygame.Rect(dx + 112, card.y, card.right - 14 - (dx + 112), 100)
    tag = status_tag(ch)
    name_r = cv.text(ch.name.upper(), head.x, dy + 34, 26, GOLD, bold=True,
                     box=pygame.Rect(head.x, head.y, head.width - (80 if tag else 0), 40), min_size=18)
    if tag:
        cv.chip(name_r.right + 10, dy + 38, tag[0], True, tag[1], 14, box=card)
    sex = sex_word(ch.sex)
    line = f"{words(ch.race)} {words(ch.profession)}  ·  {sex}  ·  Level {ch.level}"
    cv.text(line, head.x, dy + 68, 16, FG, box=head)
    vitals = f"HP {ch.hp}/{ch.max_hp}   MP {ch.mp}/{ch.max_mp}   Food {ch.food}   Gold {ch.gold}"
    cv.text(vitals, head.x, dy + 92, 15, DIM, box=head)
    caps = (ch.race.max_str, ch.race.max_dex, ch.race.max_int, ch.race.max_wis)
    vals = (ch.strength, ch.dexterity, ch.intelligence, ch.wisdom)
    for k, (lab, v, cap) in enumerate(zip(STAT_SHORT, vals, caps)):
        y = dy + 140 + k * 30
        cv.text(lab, dx + 18, y - 4, 15, DIM, box=card)
        cv.text(str(v), dx + 92, y - 4, 17, FG, align="right", box=card)
        bx, bw = dx + 104, 250
        pygame.draw.rect(s, BAR_BG, (bx, y + 2, bw, 10), border_radius=3)
        pygame.draw.rect(s, LINE, (bx + int(bw * cap / 99) - 1, y, 2, 14))
        fill = int(bw * min(v, 99) / 99)
        if fill > 0:
            pygame.draw.rect(s, BAR, (bx, y + 2, fill, 10), border_radius=3)
        cv.text(f"race max {cap}", card.right - 16, y - 3, 13, DIM, align="right", box=card)
    weapon_names, armor_names = names
    cv.text("Readied", dx + 18, dy + 262, 14, DIM, box=card)
    w1 = cv.chip(dx + 84, dy + 260, gear_name(ch.weapon, weapon_names), True, box=card)
    worn_x = max(dx + 190, dx + 84 + w1 + 18)
    wr = cv.text("Worn", worn_x, dy + 262, 14, DIM, box=card)
    cv.chip(wr.right + 12, dy + 260, gear_name(ch.armor, armor_names), True, box=card)
    cv.text("Marks", dx + 18, dy + 298, 14, DIM, box=card)
    x = dx + 84
    marks = list(getattr(ch, "marks", None) or [0, 0, 0, 0])
    for i, m in enumerate(MARK_NAMES):
        lit = i < len(marks) and bool(marks[i])
        x += cv.chip(x, dy + 296, m, lit, box=card) + 6


def _render_roster_small(s: pygame.Surface, scr: Any) -> Canvas:
    """320x200: text rows only, no detail card."""
    s.fill(BG)
    cv = Canvas(s)
    w, h = s.get_size()
    cv.text(TITLE_MAIN, 4, 1, 13, GOLD, bold=True)
    count = len(scr.roster)
    cv.text(f"ROSTER {count}/20", w - 4, 3, 9, DIM, align="right")
    # The party on one line.
    x = 4
    members = scr.party.members
    for i in range(4):
        if i < len(members):
            ch = getattr(members[i], "character", members[i])
            label = f"{i + 1} {ch.name.upper()}"
            col = GOLD
        else:
            label, col = f"{i + 1} open", EMPTY_INK
        cell = pygame.Rect(4 + i * 78, 17, 76, 12)
        if scr.focus_panel == "party" and scr.selected_party_idx == i:
            pygame.draw.rect(s, SEL, cell)
        cv.text(label, cell.x + 2, cell.y, 10, col, box=cell)
        x += 78
    # Ten roster rows.
    offset = scr.roster_scroll_offset
    top, rh = 32, 12
    for row in range(VISIBLE_ROWS):
        idx = offset + row
        y = top + row * rh
        rr = pygame.Rect(2, y, w - 4, rh)
        selected = idx == scr.selected_roster_idx and count > 0
        if selected:
            if scr.focus_panel == "roster":
                pygame.draw.rect(s, SEL, rr)
            pygame.draw.rect(s, GOLD if scr.focus_panel == "roster" else LINE, rr, 1)
        cv.text(f"{idx + 1:>2}", 18, y, 10, DIM, align="right", box=rr)
        if idx < count:
            ch = scr.roster[idx]
            cv.text(ch.name.upper(), 22, y, 10, GOLD if selected else FG, box=pygame.Rect(22, y, 82, rh))
            cv.text(f"{words(ch.race)} {words(ch.profession)}", 106, y, 10, DIM, box=pygame.Rect(106, y, 110, rh))
            cv.text(f"Lv {ch.level}", 218, y, 10, DIM, box=pygame.Rect(218, y, 30, rh))
            tags = []
            if scr._in_party(ch):
                tags.append(("party", CYAN))
            tag = status_tag(ch)
            if tag:
                tags.append(tag)
            tx = 250
            for word, col in tags:
                tx = cv.text(word, tx, y, 10, col, box=pygame.Rect(250, y, w - 254, rh)).right + 3
        else:
            cv.text("·  empty", 26, y, 10, EMPTY_INK)
    above, below = scroll_hints(offset, count)
    hint = "  ".join(t for t in (above, below) if t)
    y = top + VISIBLE_ROWS * rh + 1
    if hint:
        cv.text(hint, 22, y, 9, FAINT)
    msg, asking = _message_line(scr)
    if msg:
        cv.text(msg, 4, y + 11, 10, GOLD if asking else DIM, box=pygame.Rect(2, y + 10, w - 4, 12))
    keys1 = "A add  R remove  C create  D delete  X disperse"
    keys2 = "P save  Tab party/roster  Enter set out  Esc back"
    cv.text(keys1, 4, h - 25, 10, CYAN, box=pygame.Rect(2, h - 26, w - 4, 12))
    cv.text(keys2, 4, h - 13, 10, CYAN, box=pygame.Rect(2, h - 14, w - 4, 12))
    return cv


# -- A NEW ADVENTURER ------------------------------------------------------


def creation_hint(step: int) -> str:
    """The key line under the title for creation step ``step`` (0-4)."""
    head = f"Step {step + 1} of 5"
    if step == 0:
        return f"{head}  ·  Type a name  ·  Enter next  ·  Esc cancel"
    if step < 4:
        return f"{head}  ·  Up/Down choose (or type the letter)  ·  Enter next  ·  Esc back"
    return f"{head}  ·  Up/Down choose  ·  Left/Right adjust  ·  Enter accept  ·  Esc back"


def render_creation(surface: pygame.Surface, scr: Any, names: tuple[dict, dict] = ({}, {})) -> Canvas:
    w, h = surface.get_size()
    view = scr.creation_view()
    if w < 640:
        return _render_creation_small(surface, scr, view)
    if (w, h) == (960, 600):
        return _render_creation_full(surface, scr, view, names)
    big = pygame.Surface((960, 600))
    cv = _render_creation_full(big, scr, view, names)
    surface.blit(pygame.transform.smoothscale(big, (w, h)), (0, 0))
    return cv


def _preview_char(view: dict) -> Any:
    from py_exodus.entities.character import Character

    prof = view["prof"]
    if prof is None:
        return None
    st = view["stats"]
    return Character(view["name"] or "?", view["sex"] or Sex.MALE, view["race"] or Race.HUMAN, prof,
                     strength=st[0], dexterity=st[1], intelligence=st[2], wisdom=st[3])


def _render_creation_full(s: pygame.Surface, scr: Any, view: dict, names: tuple[dict, dict]) -> Canvas:
    s.fill(BG)
    cv = Canvas(s)
    step = view["step"]
    cv.text(TITLE_CREATE, 32, 18, 30, GOLD, bold=True)
    cv.text(creation_hint(step), 32, 56, 15, DIM, box=pygame.Rect(32, 50, 896, 24))

    # The preview card.
    card = pygame.Rect(32, 90, 260, 450)
    pygame.draw.rect(s, PANEL, card, border_radius=8)
    pygame.draw.rect(s, EDGE, card, 2, border_radius=8)
    inner = card.inflate(-24, 0)
    prof = view["prof"]
    spot = pygame.Rect(card.x + 66, 110, 128, 128)
    img = sprite(scr.asset_mgr, prof, 128)
    if img is not None:
        s.blit(img, spot)
    else:
        _dashed_rect(s, spot, LINE)
        cv.text("?", spot.centerx, spot.y + 40, 40, LINE, align="center", box=spot)
    name = view["name"]
    cv.text(name.upper() if name else "?", card.centerx, 252, 28, GOLD if name else LINE,
            align="center", bold=True, box=inner, min_size=18)
    who = "  ·  ".join(p for p in (
        " ".join(p for p in (words(view["race"]) if view["race"] else "", words(prof) if prof else "") if p),
        sex_word(view["sex"]) if view["sex"] else "") if p)
    cv.text(who or "Choices appear here", card.centerx, 290, 17, FG if who else DIM, align="center", box=inner)
    weapon_names, armor_names = names
    lines = [("Starts with", "150 HP, food, gold"),
             ("Readied", gear_name(WeaponType.DAGGER, weapon_names)),
             ("Worn", gear_name(ArmorType.CLOTH, armor_names))]
    if prof is not None:
        bw, ba = best_gear(prof)
        lines += [("Weapons to", gear_name(bw, weapon_names)), ("Armour to", gear_name(ba, armor_names))]
        pc = _preview_char(view)
        lines.append(("MP now", str(pc.compute_max_mp())))
    for k, (a, b) in enumerate(lines):
        cv.text(a, 52, 330 + k * 32, 14, DIM, box=pygame.Rect(52, 0, 86, 600))
        cv.text(b, 140, 330 + k * 32, 15, FG, box=pygame.Rect(140, 0, card.right - 14 - 140, 600))

    # The five steps.
    values = (view["name_done"], sex_word(view["sex_done"]) if view["sex_done"] else "",
              words(view["race_done"]) if view["race_done"] else "",
              words(view["prof_done"]) if view["prof_done"] else "", "")
    x0 = 316
    for k, (lab, val) in enumerate(zip(CREATION_STEPS, values)):
        y = 90 + k * 36
        now, done = k == step, k < step
        pygame.draw.circle(s, GOLD if now else (GREEN if done else LINE), (x0 + 10, y + 12), 9)
        cv.text(str(k + 1), x0 + 10, y + 3, 14, CHIP_INK, align="center")
        cv.text(lab, x0 + 28, y + 2, 18, GOLD if now else (FG if done else DIM))
        if val:
            cv.text(val, x0 + 110, y + 3, 17, DIM, box=pygame.Rect(x0 + 110, y, 300, 30))

    panel = pygame.Rect(316, 280, 612, 260)
    pygame.draw.rect(s, PANEL, panel, border_radius=8)
    if step == 0:
        _name_panel(cv, scr, panel)
    elif step in (1, 2, 3):
        _choice_panel(cv, view, panel)
    else:
        _stats_panel(cv, view, panel)

    note = view["note"]
    if note:
        cv.text(note, 316, 552, 16, GOLD, box=pygame.Rect(316, 546, 612, 30))
    return cv


def _name_panel(cv: Canvas, scr: Any, panel: pygame.Rect) -> None:
    from py_exodus.screens.roster_screen import CREATION_MAX_NAME

    s = cv.s
    cv.text(f"Type a name, up to {CREATION_MAX_NAME} letters", panel.x + 20, panel.y + 12, 17, FG, box=panel)
    field = pygame.Rect(panel.x + 20, panel.y + 60, panel.width - 40, 52)
    pygame.draw.rect(s, BG, field, border_radius=6)
    pygame.draw.rect(s, GOLD, field, 1, border_radius=6)
    buf = scr.text_log.input_buffer
    cv.text(buf.upper() + "_", field.x + 16, field.y + 10, 26, GOLD, bold=True, box=field.inflate(-24, 0))
    cv.text(f"{len(buf)}/{CREATION_MAX_NAME}", panel.right - 20, panel.y + 124, 14, DIM, align="right", box=panel)
    cv.text("No name: the adventurer is called Hero and a number.", panel.x + 20, panel.y + 124, 14, DIM,
            box=pygame.Rect(panel.x + 20, panel.y, panel.width - 100, panel.height))


def _choice_panel(cv: Canvas, view: dict, panel: pygame.Rect) -> None:
    s = cv.s
    step = view["step"]
    opts = view["options"]
    cur = view["cursor"]
    heads = {1: "Choose a sex", 2: "Choose a race (its maximum for each stat)", 3: "Choose a class"}
    cv.text(heads[step], panel.x + 20, panel.y + 12, 17, FG, box=panel)
    cols = 2 if len(opts) > 6 else 1
    per_col = (len(opts) + cols - 1) // cols
    row_h = min(44, (panel.height - 56) // per_col)
    col_w = (panel.width - 20) // cols
    for i, (code, label, extra) in enumerate(opts):
        c, r = divmod(i, per_col)
        x = panel.x + 10 + c * col_w
        y = panel.y + 48 + r * row_h
        cell = pygame.Rect(x, y, col_w - 10, row_h - 4)
        if i == cur:
            pygame.draw.rect(s, SEL, cell, border_radius=6)
        cv.chip(cell.x + 10, cell.y + (cell.height - 22) // 2, code, i == cur, CYAN, 13, box=cell, h=22)
        cv.text(label, cell.x + 46, cell.y + (cell.height - 22) // 2, 18, GOLD if i == cur else FG,
                box=pygame.Rect(cell.x + 46, cell.y, 140, cell.height))
        if extra:
            cv.text(extra, cell.x + 190, cell.y + (cell.height - 18) // 2, 14, DIM,
                    box=pygame.Rect(cell.x + 190, cell.y, cell.right - 8 - (cell.x + 190), cell.height))


def _stats_panel(cv: Canvas, view: dict, panel: pygame.Rect) -> None:
    s = cv.s
    stats = view["stats"]
    left = view["left"]
    cv.text("Share 50 points among the four (each 5-25)", panel.x + 20, panel.y + 12, 17, FG,
            box=pygame.Rect(panel.x + 20, panel.y, panel.width - 140, 40))
    cv.text(f"{left} left", panel.right - 20, panel.y + 12, 18, GREEN if left == 0 else GOLD,
            align="right", box=panel)
    race = view["race"] or Race.HUMAN
    caps = (race.max_str, race.max_dex, race.max_int, race.max_wis)
    for k, (lab, v, cap, what) in enumerate(zip(STAT_LABELS, stats, caps, STAT_WHAT)):
        y = panel.y + 54 + k * 48
        chosen = k == view["stat_sel"]
        if chosen:
            pygame.draw.rect(s, SEL, (panel.x + 10, y - 8, panel.width - 20, 44), border_radius=6)
        cv.text(lab, panel.x + 20, y, 18, GOLD if chosen else FG, box=pygame.Rect(panel.x + 20, y, 130, 30))
        cv.text("<", panel.x + 154, y, 18, CYAN)
        cv.text(str(v), panel.x + 190, y, 20, FG, align="center")
        cv.text(">", panel.x + 216, y, 18, CYAN)
        for b in range(25):
            col = BAR if b < v else BLOCK_OFF
            pygame.draw.rect(s, col, (panel.x + 240 + b * 10, y + 6, 8, 12))
        tbox = pygame.Rect(panel.x + 496, y - 4, panel.right - 10 - (panel.x + 496), 40)
        cv.text(what, tbox.x, y + 2, 13, DIM, box=tbox)
        cv.text(f"race max {cap}", tbox.x, y + 18, 12, FAINT, box=tbox)


def _render_creation_small(s: pygame.Surface, scr: Any, view: dict) -> Canvas:
    s.fill(BG)
    cv = Canvas(s)
    w, h = s.get_size()
    step = view["step"]
    cv.text(TITLE_CREATE, 4, 1, 13, GOLD, bold=True)
    cv.text(f"Step {step + 1} of 5", w - 4, 3, 9, DIM, align="right")
    values = (view["name_done"], sex_word(view["sex_done"]) if view["sex_done"] else "",
              words(view["race_done"]) if view["race_done"] else "",
              words(view["prof_done"]) if view["prof_done"] else "", "")
    y = 18
    for k, (lab, val) in enumerate(zip(CREATION_STEPS, values)):
        col = GOLD if k == step else (FG if k < step else DIM)
        cv.text(f"{k + 1} {lab}", 4, y, 10, col)
        if val:
            cv.text(val, 60, y, 10, DIM, box=pygame.Rect(60, y, 100, 12))
        y += 11
    box = pygame.Rect(2, 76, w - 4, 98)
    y = box.y
    if step == 0:
        cv.text("Type a name, Enter to go on:", 4, y, 10, FG, box=box)
        cv.text(scr.text_log.input_buffer.upper() + "_", 4, y + 14, 13, GOLD, bold=True, box=box)
    elif step in (1, 2, 3):
        opts = view["options"]
        cols = 2 if len(opts) > 6 else 1
        per_col = (len(opts) + cols - 1) // cols
        col_w = box.width // cols
        for i, (code, label, extra) in enumerate(opts):
            c, r = divmod(i, per_col)
            cell = pygame.Rect(box.x + c * col_w, y + r * 12, col_w - 2, 12)
            if i == view["cursor"]:
                pygame.draw.rect(s, SEL, cell)
            text = f"{code}  {label}" + (f"  {extra}" if extra and cols == 1 else "")
            cv.text(text, cell.x + 2, cell.y, 10, GOLD if i == view["cursor"] else FG, box=cell)
    else:
        left = view["left"]
        cv.text(f"Share 50 (each 5-25): {left} left", 4, y, 10, GREEN if left == 0 else GOLD, box=box)
        for k, (lab, v) in enumerate(zip(STAT_SHORT, view["stats"])):
            cell = pygame.Rect(box.x, y + 14 + k * 13, box.width, 12)
            if k == view["stat_sel"]:
                pygame.draw.rect(s, SEL, cell)
            cv.text(f"{lab}  < {v:>2} >", 6, cell.y, 10, GOLD if k == view["stat_sel"] else FG, box=cell)
            pygame.draw.rect(s, BAR, (90, cell.y + 3, 4 * v, 6))
    if view["note"]:
        cv.text(view["note"], 4, h - 25, 10, GOLD, box=pygame.Rect(2, h - 26, w - 4, 12))
    keys = ("Type a name  Enter next  Esc cancel", "Up/Down choose  Enter next  Esc back",
            "Up/Down choose  Left/Right adjust  Enter accept  Esc back")[0 if step == 0 else 2 if step == 4 else 1]
    cv.text(keys, 4, h - 13, 10, CYAN, box=pygame.Rect(2, h - 14, w - 4, 12))
    return cv
