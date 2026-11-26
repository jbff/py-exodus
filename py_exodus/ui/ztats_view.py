"""The Ztats window (approved design C, 2026-11-23).

Z asks whose stats (LairWare Stats, UltimaMain.c:2592-2602) and DoStats
(UltimaMacIF.c:1385-1395) shows them until any key: the port draws them as
a modal window over the MAP PANE only, the map dimmed behind it, while the
party panel and the message log stay up. The window holds the member's class
sprite, who they are, HP/MP bars, XP/food/gold, carried supplies, four stat
tiles saying what each stat does for this member (from the combat and MP
rules, never sample numbers), weapon and armour chips (gold: readied/worn),
the member's marks and cards, and the spell book(s) of their discipline(s).

At 320x200 the pane is 176 px: a simplified text layout (no sprite, tiles
or chips) keeps the same facts in short lines.
"""
from __future__ import annotations

from typing import Any

import pygame

from py_exodus.combat.resolver import hit_chance, player_damage_range
from py_exodus.constants import ArmorType, Spell, WeaponType
from py_exodus.ui import party_panel as pp
from py_exodus.ui.party_panel import _Flow, _title
from py_exodus.ui.text_log import get_hud_font

FOOTER = "Any key closes  ·  game paused"
SHADE = (0, 0, 0, 170)
WINDOW_BG = (10, 10, 12)
TILE_BG = (24, 24, 24)
# A spell the member could cast but lacks the MP for right now.
SPELL_DIM = (60, 110, 130)
DISCIPLINE_LABEL = {"wizard": "Wizard", "cleric": "Cleric"}
BOOK_TITLE = {"wizard": "SORCERY", "cleric": "PRAYERS"}
SPELL_LEGEND = "(lit: castable now · dim: needs MP)"


# -- what the window shows (pure, tested) -----------------------------------


def window_rect(pane: pygame.Rect) -> pygame.Rect:
    """The window inside the map pane: the mockup's margins at 960x600
    (14 px sides, 18 px top/bottom of the 528 px pane), scaled down."""
    k = pane.width / 528.0
    return pane.inflate(-max(4, round(28 * k)), -max(4, round(36 * k)))


def stat_tiles(member: Any) -> list[tuple[str, int, str]]:
    """(label, value, what it does) for STR, DEX, INT and WIS: the readied
    weapon's damage range, the to-hit chance, and the MP max INT and WIS
    give this member's class ("-" when they give none)."""
    low, high = player_damage_range(member)
    from_int, from_wis = member.mp_max_parts()
    both = from_int is not None and from_wis is not None
    which = ", lower" if getattr(member.profession, "name", "") == "RANGER" else ", higher"

    def mp(part: int | None) -> str:
        if part is None:
            return "-"
        return f"MP max {part}" + (which if both else "")

    return [
        ("STR", member.str, f"dmg {low}–{high}"),
        ("DEX", member.dex, f"hit {round(100 * hit_chance(member.dex))}%"),
        ("INT", member.int, mp(from_int)),
        ("WIS", member.wis, mp(from_wis)),
    ]


def gear_chips(counts: dict, enum_cls: type, names: dict, readied: Any) -> list[tuple[str, bool]]:
    """(label, readied) per owned item kind, with "x2" counts, and the
    readied one even when the pack holds no spare. Bare hands or skin show
    as the readied chip when nothing else is."""
    chips = []
    none = getattr(enum_cls, "NONE")
    if readied == none or readied is None:
        chips.append((names.get("NONE", "None"), True))
    for kind in enum_cls:
        n = counts.get(kind, 0)
        if kind == none or (n <= 0 and kind != readied):
            continue
        label = names.get(kind.name, _title(kind))
        if kind.name == "EXOTIC":
            label = "Exotic"
        chips.append((label + (f" ×{n}" if n > 1 else ""), kind == readied))
    return chips


def spell_books(member: Any) -> list[tuple[str, list[tuple[Spell, str]]]]:
    """Per discipline the member casts: each spell with its state, "lit"
    (castable now with the MP in hand), "dim" (within the MP max, needs
    MP) or "off" (beyond this member: over the MP max or not the class)."""
    from py_exodus.combat.magic import get_castable_spell_types

    books = []
    for discipline in get_castable_spell_types(member.profession):
        spells = []
        for spell in sorted((s for s in Spell if s.spell_type == discipline), key=lambda s: s.code):
            if spell.cost > member.max_mp or not spell.can_cast(member.profession):
                state = "off"
            elif spell.cost <= member.mp:
                state = "lit"
            else:
                state = "dim"
            spells.append((spell, state))
        books.append((discipline, spells))
    return books


def status_tag(member: Any) -> str | None:
    """POISONED / DEAD / ASHES as the party panel tags them, else None."""
    look = pp.STATUS_LOOK.get(member.status)
    return look[1] if look else None


# -- drawing ---------------------------------------------------------------


def _sprite(asset_mgr: Any, member: Any) -> pygame.Surface | None:
    if asset_mgr is None:
        return None
    try:
        return asset_mgr.get_tile_surface(member.profession.tile)
    except Exception:  # noqa: BLE001 - a missing tile just leaves the space
        return None


class _Fonts:
    def __init__(self, k: float) -> None:
        size = lambda px: max(9, int(round(px * k)))  # noqa: E731
        self.name = get_hud_font(size(19), pp.BOLD_FONT)
        self.body = get_hud_font(size(14))
        self.small = get_hud_font(size(12), pp.BOLD_FONT)
        self.bold = get_hud_font(size(14), pp.BOLD_FONT)
        self.big = get_hud_font(size(30), pp.BOLD_FONT)
        self.tiny = get_hud_font(size(12))


def render_ztats(
    surface: pygame.Surface,
    pane: pygame.Rect,
    member: Any,
    number: int,
    asset_mgr: Any = None,
    names: tuple[dict, dict] = ({}, {}),
) -> pygame.Rect:
    """Dim the map pane and draw member ``number`` (1-4)'s Ztats window in
    it. Nothing outside ``pane`` is touched. Returns the window rect."""
    pane = pygame.Rect(pane)
    shade = pygame.Surface(pane.size, pygame.SRCALPHA)
    shade.fill(SHADE)
    surface.blit(shade, pane.topleft)
    win = window_rect(pane)
    prev_clip = surface.get_clip()
    surface.set_clip(pane)
    try:
        k = pane.width / 528.0
        pygame.draw.rect(surface, WINDOW_BG, win, border_radius=max(2, round(4 * k)))
        pygame.draw.rect(surface, pp.GOLDEN, win, width=max(1, round(2 * k)),
                         border_radius=max(2, round(4 * k)))
        if pane.width >= 400:
            _render_full(surface, win, member, number, asset_mgr, names, _Fonts(k))
        else:
            _render_small(surface, win, member, number, names)
    finally:
        surface.set_clip(prev_clip)
    return win


def _header(s, f: _Fonts, m, x, y, w) -> int:
    """Name, status tag, and race/class/sex/level right-aligned."""
    img = f.name.render(m.name.upper(), True, pp.WHITE)
    s.blit(img, (x, y))
    look = pp.STATUS_LOOK.get(m.status)
    if look:
        tag = f.small.render(look[1], True, look[3])
        tr = pygame.Rect(x + img.get_width() + 6, y + (img.get_height() - tag.get_height()) // 2,
                         tag.get_width() + 8, tag.get_height())
        pygame.draw.rect(s, look[2], tr, border_radius=2)
        s.blit(tag, (tr.x + 4, tr.y))
    sex = getattr(m.sex, "value", m.sex)
    who = f.body.render(f"{_title(m.race)} {_title(m.profession)} · {sex} · Lv {m.level}",
                        True, pp.WHO)
    s.blit(who, (x + w - who.get_width(), y + img.get_height() - who.get_height()))
    return y + img.get_height() + 2


def _kv(fl: _Flow, f: _Fonts, label: str, value: str, faint: bool = False) -> None:
    fl.text(f.body, label, pp.INK, tight=True)
    fl.text(f.bold, value, pp.FAINT if faint else pp.WHITE)


def _section(s, x, y, w, title, body, line_h, gap=12) -> int:
    """A framed section: optional pre-rendered title, then a flow body."""
    top = y
    y += 5
    if title is not None:
        s.blit(title, (x + 7, y))
        y += title.get_height()
    fl = _Flow(s, x + 7, y, w - 14, line_h, gap)
    body(fl)
    y = fl.bottom() + 5
    pygame.draw.rect(s, pp.SECTION, (x, top, w, y - top), width=1, border_radius=2)
    return y + 6


def _render_full(s, win, m, number, asset_mgr, names, f: _Fonts) -> None:
    weapon_names, armor_names = names
    line = f.body.get_linesize() + 5
    pad = 16
    left, full = win.x + pad, win.width - 2 * pad

    # Banner on the top edge.
    banner = f.small.render(f"ZTATS · {number}", True, (0, 0, 0))
    br = pygame.Rect(left, win.y - banner.get_height() // 2 - 1,
                     banner.get_width() + 14, banner.get_height() + 2)
    br.y = max(br.y, s.get_clip().y)
    pygame.draw.rect(s, pp.GOLDEN, br, border_radius=3)
    s.blit(banner, (br.x + 7, br.y + 1))

    # Class sprite, big and blocky.
    spr = _sprite(asset_mgr, m)
    if spr is not None:
        s.blit(pygame.transform.scale(spr, (96, 96)), (left, win.y + 16))
    x = win.x + 128
    w = win.right - pad - x
    y = _header(s, f, m, x, win.y + 18, w)

    fl = _Flow(s, x, y + 4, w, line, 9)
    fl.text(f.body, "HP", pp.INK, tight=True)
    fl.bar(m.hp / m.max_hp if m.max_hp else 0, pp.HP_RED, w=110)
    fl.text(f.bold, f"{m.hp}/{m.max_hp}", pp.WHITE)
    fl.text(f.body, "MP", pp.INK, tight=True)
    if m.max_mp > 0:
        fl.bar(m.mp / m.max_mp, pp.MP_BLUE, w=80)
        fl.text(f.bold, f"{m.mp}/{m.max_mp}", pp.WHITE)
    else:
        fl.text(f.bold, "-", pp.FAINT)
    fl.newline()
    _kv(fl, f, "XP", f"{m.exp:,}")
    _kv(fl, f, "Food", f"{m.food:,}")
    _kv(fl, f, "Gold", f"{m.gold:,}")
    fl.newline()
    for label, v in (("Keys", m.keys), ("Gems", m.gems), ("Torches", m.torches),
                     ("Powders", m.powder)):
        _kv(fl, f, label, str(v), faint=not v)
    y = max(fl.bottom(), win.y + 118) + 6

    # Stat tiles.
    gap, th = 6, 62
    tw = (full - 3 * gap) // 4
    for i, (label, value, hint) in enumerate(stat_tiles(m)):
        r = pygame.Rect(left + i * (tw + gap), y, tw, th)
        pygame.draw.rect(s, TILE_BG, r, border_radius=3)
        pygame.draw.rect(s, pp.FRAME, r, width=1, border_radius=3)
        s.blit(f.small.render(label, True, pp.HEADER), (r.x + 7, r.y + 4))
        v = f.big.render(str(value), True, pp.WHITE)
        s.blit(v, (r.right - v.get_width() - 7, r.y + 1))
        h = f.tiny.render(hint, True, pp.DIM)
        s.blit(h, (r.x + 7, r.bottom - h.get_height() - 4))
    y += th + 8

    def chips(items):
        def body(fl):
            for label, on in items:
                fl.chip(f.body, label, pp.GEAR if on else None)
        return body

    half = (full - 8) // 2
    head = lambda t: f.small.render(t, True, pp.HEADER)  # noqa: E731
    yl = _section(s, left, y, half, head("WEAPONS  (gold: readied)"),
                  chips(gear_chips(m.weapons, WeaponType, weapon_names, m.weapon)), line, 9)
    yr = _section(s, left + half + 8, y, half, head("ARMOUR  (gold: worn)"),
                  chips(gear_chips(m.armors, ArmorType, armor_names, m.armor)), line, 9)
    y = max(yl, yr)

    def quest(fl):
        fl.text(f.body, "Marks", pp.INK)
        for label, i in pp.MARKS:
            fl.chip(f.body, label, pp.MARK_ON if m.marks[i] else None)
        fl.newline()
        fl.text(f.body, "Cards", pp.INK)
        for label, i in pp.CARDS:
            fl.chip(f.body, label, pp.CARD_ON if m.cards[i] else None)

    y = _section(s, left, y, full, head("QUEST"), quest, line + 2)

    books = spell_books(m)
    colour = {"lit": pp.MP_BLUE, "dim": SPELL_DIM, "off": None}
    tiny_line = f.tiny.get_linesize() + 7
    if len(books) == 1:
        discipline, spells = books[0]
        from py_exodus.screens.quickref import spell_display_name

        def book(fl):
            for spell, state in spells:
                fl.chip(f.tiny, f"{spell.code} {spell_display_name(spell)} {spell.cost}",
                        colour[state])

        _section(s, left, y, full, head(f"{BOOK_TITLE[discipline]}  {SPELL_LEGEND}"),
                 book, tiny_line, 6)
    elif books:
        # Druids and Rangers cast both: a row of lettered chips per book
        # (MP is 5 a letter from A at 0; names are on the F4 cards).
        def both(fl):
            for discipline, spells in books:
                fl.text(f.body, DISCIPLINE_LABEL[discipline], pp.INK)
                for spell, state in spells:
                    fl.chip(f.tiny, spell.code, colour[state])
                fl.newline()

        _section(s, left, y, full, head(f"SPELLS  {SPELL_LEGEND}"), both, tiny_line + 2, 5)

    foot = f.tiny.render(FOOTER, True, pp.FAINT)
    s.blit(foot, (win.centerx - foot.get_width() // 2, win.bottom - foot.get_height() - 6))


def _render_small(s, win, m, number, names) -> None:
    """320x200: short text lines, no sprite, tiles or chips."""
    weapon_names, armor_names = names
    f_name = get_hud_font(12, pp.BOLD_FONT)
    f = get_hud_font(10)
    x, y = win.x + 4, win.y + 3

    def line(text, colour=pp.INK, font=f):
        nonlocal y
        img = font.render(text, True, colour)
        s.blit(img, (x, y))
        y += font.get_linesize()
        return img

    name = line(f"{number} {m.name.upper()}", pp.WHITE, f_name)
    tag = status_tag(m)
    if tag:
        look = pp.STATUS_LOOK[m.status]
        t = f.render(tag, True, look[3])
        tr = pygame.Rect(x + name.get_width() + 4, y - f_name.get_linesize() + 2,
                         t.get_width() + 4, t.get_height())
        pygame.draw.rect(s, look[2], tr)
        s.blit(t, (tr.x + 2, tr.y))
    sex = getattr(m.sex, "value", m.sex)
    line(f"{_title(m.race)} {_title(m.profession)} {sex} Lv {m.level}", pp.WHO)
    mp = f"{m.mp}/{m.max_mp}" if m.max_mp > 0 else "-"
    line(f"HP {m.hp}/{m.max_hp}  MP {mp}", pp.WHITE)
    line(f"XP {m.exp}  Food {m.food}  Gold {m.gold}")
    tiles = stat_tiles(m)
    line("  ".join(f"{lab[0]} {val}" for lab, val, _ in tiles), pp.WHITE)
    line(f"{tiles[0][2]}  {tiles[1][2]}", pp.DIM)
    wname = weapon_names.get(getattr(m.weapon, "name", "NONE"), _title(m.weapon))
    aname = armor_names.get(getattr(m.armor, "name", "NONE"), _title(m.armor))
    line(f"Wpn {wname}", pp.GEAR)
    line(f"Arm {aname}", pp.GEAR)
    line(f"Keys {m.keys} Gems {m.gems} Tor {m.torches} Pow {m.powder}")
    marks = " ".join(lab for lab, i in pp.MARKS if m.marks[i]) or "-"
    cards = " ".join(lab for lab, i in pp.CARDS if m.cards[i]) or "-"
    line(f"Marks {marks}", pp.MARK_ON)
    line(f"Cards {cards}", pp.CARD_ON)
    foot = f.render("Any key closes", True, pp.FAINT)
    s.blit(foot, (win.centerx - foot.get_width() // 2, win.bottom - foot.get_height() - 2))
