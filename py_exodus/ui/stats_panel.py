"""Party Stats Panel and Character Inspection Sidebar for Ultima III HUD."""
from __future__ import annotations

import pygame

from py_exodus.constants import ArmorType, Transport, WeaponType
from py_exodus.entities.party import Party
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


# Mark and card row pairs in Java zstats order (exodus/Party.java:703-711):
# "MARK KINGS"/"MARK FIRE", "MARK SNAKE"/"MARK FORCE", "CARD DEATH"/"CARD SOL",
# "CARD MOONS"/"CARD LOVE" over marks[0..3] and cards[0..3].
MARK_CARD_ROW_PAIRS = (
    ("MARK KINGS", 0, "MARK FIRE", 1, "marks"),
    ("MARK SNAKE", 2, "MARK FORCE", 3, "marks"),
    ("CARD DEATH", 0, "CARD SOL", 1, "cards"),
    ("CARD MOONS", 2, "CARD LOVE", 3, "cards"),
)


def _zstats_cell(label: str, values: list[int], idx: int) -> str | None:
    """One "LABEL: n" cell, or None when 0 (Java shows only non-zero counts)."""
    if idx < len(values) and values[idx] > 0:
        return f"{label}: {values[idx]}"
    return None


def mark_and_card_rows(pm: object) -> list[str]:
    """Zstats MARK/CARD rows for a party member (exodus/Party.java:703-715)."""
    rows = []
    for label_l, i_l, label_r, i_r, field in MARK_CARD_ROW_PAIRS:
        values = getattr(pm, field, None) or []
        cells = [
            cell
            for cell in (_zstats_cell(label_l, values, i_l), _zstats_cell(label_r, values, i_r))
            if cell
        ]
        if cells:
            rows.append("  ".join(cells))
    return rows


def _pair_list_rows(cells: list[str], per_row: int = 2) -> list[str]:
    """Inventory entries packed per_row per line, Java-style prefixed rows
    (exodus/Party.java:673-697 pairs two entries per line; the sidebar asks
    for 3 at the 3x resolution so the whole listing fits)."""
    return [" " + "  ".join(cells[i : i + per_row]) for i in range(0, len(cells), per_row)]# Lazily loaded display names for when StatsPanel has no AssetManager.
_NAMES_CACHE: tuple[dict[str, str], dict[str, str]] | None = None


def _equipment_display_names(
    asset_mgr: object | None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Display names by enum key from weapons.xml / armors.xml (Java renders
    ``WeaponType.getWeapon().getName()``, e.g. "2-Handed Sword"). Uses the
    panel's AssetManager when available, else a lazily built one, with empty
    dicts (raw enum names) when the XML cannot be read."""
    global _NAMES_CACHE

    def _from(mgr: object) -> tuple[dict[str, str], dict[str, str]] | None:
        try:
            weapons = {
                getattr(d, "type", k).upper(): getattr(d, "name", k)
                for k, d in mgr.weapons.items()
            }
            armors = {
                getattr(d, "type", k).upper(): getattr(d, "name", k)
                for k, d in mgr.armors.items()
            }
        except Exception:
            return None
        if weapons and armors:
            return weapons, armors
        return None

    if asset_mgr is not None:
        got = _from(asset_mgr)
        if got is not None:
            return got
    if _NAMES_CACHE is None:
        try:
            from py_exodus.assets import AssetManager

            mgr = AssetManager()
            mgr.load_xml_definitions()
            got = _from(mgr)
            _NAMES_CACHE = got if got is not None else ({}, {})
        except Exception:
            _NAMES_CACHE = ({}, {})
    return _NAMES_CACHE


def _java_equipment_rows(
    counts: dict,
    enum_cls: type,
    names: dict[str, str],
    per_row: int = 2,
) -> list[str]:
    """Java's exact zstats listing rule (exodus/Party.java:673-697): every
    standard type EXCEPT NONE is listed with its count — even 0 — and the
    EXOTIC entry is appended only when its count is > 0. Cells go per_row
    per line (2 in Java; the sidebar asks for 3 at 3x to fit)."""
    std = [e for e in enum_cls if e not in (enum_cls.NONE, enum_cls.EXOTIC)]
    cells = [f"{names.get(e.name, e.name)}: {counts.get(e, 0)}" for e in std]
    exotic = enum_cls.EXOTIC if hasattr(enum_cls, "EXOTIC") else None
    if exotic is not None and counts.get(exotic, 0) > 0:
        cells.append(f"{names.get(exotic.name, exotic.name)}: {counts[exotic]}")
    return _pair_list_rows(cells, per_row)


def inspect_rows(
    pm: object,
    asset_mgr: object | None = None,
    per_row: int = 2,
) -> list[str]:
    """Zstats inspection rows for one member, in Java getZstats order
    (exodus/Party.java:669-715): the name/race/class/sex/status identity
    line, HEALTH/MAXHEALTH, MANA/LV, the STR/DEX/INT/WIS stat pairs with
    EXP, the readied weapon and worn armor, torch/gem/key/powder counts,
    per-member GOLD and FOOD, then the full armor and weapon inventory
    listings and the mark/card rows.

    Ruled (review round 1): the compact WPN:/ARM:/TORCH:/KEYS: label
    abbreviations STAY — the 320x200 panel width cannot fit Java's full
    READIED/WORN/TORCHES labels — and the identity line keeps its uppercase
    compact style. Inventory values carry the XML display names ("2-Handed
    Sword") under Java's listing rule: standard types always, even 0-count,
    and EXOTIC only when > 0 (see _java_equipment_rows). EXP rides with the
    INT/WIS row and the inventory packs per_row cells per line (2, Java's
    pairing; the 3x sidebar asks for 3) so the rows down to the last
    mark/card fit the ~600px panel.
    """
    race = getattr(getattr(pm, "race", None), "name", "")
    sex = getattr(getattr(pm, "sex", None), "value", "")
    prof = getattr(getattr(pm, "profession", None), "name", "")
    status = getattr(pm.status, "value", str(pm.status))
    st = status[0].upper() if status else "?"
    name = str(getattr(pm, "name", "")).upper()
    rows = [
        f"{name} {race} {sex} {prof} ST:{st}",
        f"HP:{pm.hp}/{pm.max_hp}",
        f"MANA:{pm.mp} LV:{pm.level}",
        f"STR:{pm.str} DEX:{pm.dex}",
        f"INT:{pm.int} WIS:{pm.wis} EXP:{pm.exp}",
        f"WPN: {getattr(pm.weapon, 'value', str(pm.weapon))}",
        f"ARM: {getattr(pm.armor, 'value', str(pm.armor))}",
        f"TORCH:{pm.torches} GEMS:{pm.gems}",
        f"KEYS:{pm.keys} POWD:{pm.powder}",
        f"GOLD:{pm.gold} FOOD:{pm.food}",
    ]
    weap_names, arm_names = _equipment_display_names(asset_mgr)
    rows.extend(_java_equipment_rows(pm.armors, ArmorType, arm_names, per_row))
    rows.extend(_java_equipment_rows(pm.weapons, WeaponType, weap_names, per_row))
    rows.extend(mark_and_card_rows(pm))
    return rows


def inspect_row_color(row: str) -> tuple[int, int, int]:
    """Draw color for an inspect row: inventory gray, supplies/mark rows green."""
    if row.startswith(" "):
        return EGA_LIGHT_GRAY
    if row.startswith(("MARK", "CARD", "TORCH", "KEYS")):
        return EGA_BRIGHT_GREEN
    return EGA_WHITE


class StatsPanel:
    """Renders the party sidebar with member stats, status conditions, active transport,

    and detailed item/stat inspection mode (torches, gems, keys, powder, equipment).
    """

    def __init__(
        self,
        font: pygame.font.Font | None = None,
        small_font: pygame.font.Font | None = None,
        inspect_index: int | None = None,
        asset_mgr: object | None = None,
    ) -> None:
        self.font = font
        self.small_font = small_font
        self.inspect_index: int | None = inspect_index
        # Optional AssetManager for XML equipment display names in zstats.
        self.asset_mgr = asset_mgr

    def set_inspect(self, index: int | None) -> None:
        """Set or clear member inspection mode (0-3 for member, -1 for pooled party supplies)."""
        self.inspect_index = index

    def render(
        self,
        surface: pygame.Surface,
        party: Party,
        inspect_index: int | None = None,
        rect: pygame.Rect | tuple[int, int, int, int] | None = None,
        draw_border: bool = True,
    ) -> None:
        """Render party status sidebar to surface."""
        w, h = surface.get_width(), surface.get_height()

        # Compute sidebar target rect (right portion of screen)
        if rect is None:
            if w <= 320:
                target_rect = pygame.Rect(176, 0, w - 176, h)
            else:
                scale = w / 320.0
                target_rect = pygame.Rect(int(176 * scale), 0, w - int(176 * scale), h)
        else:
            target_rect = pygame.Rect(rect)

        # Fill background
        surface.fill(EGA_BLACK, target_rect)
        if draw_border:
            pygame.draw.rect(surface, EGA_DARK_GRAY, target_rect, width=1)

        # Dynamic font sizing based on target width
        is_large = target_rect.width >= 240
        f_title = self.font or get_hud_font(size=22 if is_large else 14)
        f_text = self.small_font or get_hud_font(size=18 if is_large else 12)

        line_h = max(10, f_text.get_linesize())
        x_left = target_rect.x + (10 if is_large else 4)
        curr_y = target_rect.y + (6 if is_large else 3)

        def draw_line(
            text: str,
            col: tuple[int, int, int] = EGA_WHITE,
            use_title_font: bool = False,
        ) -> None:
            nonlocal curr_y
            f = f_title if use_title_font else f_text
            txt_surf = f.render(text, False, col)
            surface.blit(txt_surf, (x_left, curr_y))
            curr_y += f.get_linesize() + (2 if is_large else 1)

        def draw_separator() -> None:
            nonlocal curr_y
            sep_y = curr_y + (2 if is_large else 1)
            pygame.draw.line(
                surface,
                EGA_DARK_GRAY,
                (target_rect.x + 2, sep_y),
                (target_rect.right - 2, sep_y),
            )
            curr_y += 5 if is_large else 3

        # In member-inspect mode the panel becomes the single-member zstats
        # page (exodus/Party.java getZstats): the party header strip and the
        # 4-member summary are suppressed so the stat rows plus the complete
        # equipment listings down to the mark/card rows fit the panel height.
        member_inspect_index = (
            inspect_index if inspect_index is not None else self.inspect_index
        )
        member_inspect_active = (
            member_inspect_index is not None and 0 <= member_inspect_index < len(party.members)
        )
        if not member_inspect_active:
            # 1. Party Header with Count
            party_count_str = f"PARTY ({len(party.members)}/4)"
            draw_line(party_count_str, EGA_YELLOW, use_title_font=True)

            # 2. Transport Header
            trans_name = "FOOT"
            if party.transport == Transport.SHIP:
                trans_name = f"SHIP (HULL:{party.ship_hull})"
            elif party.transport == Transport.HORSE:
                trans_name = "HORSE"
            draw_line(f"TRANS: {trans_name}", EGA_BRIGHT_CYAN)

            # 3. Pooled Resources (Food & Gold)
            draw_line(f"FOOD:{party.food:<5} GOLD:{party.gold}", EGA_WHITE)
            draw_separator()

            # 4. Party Members (up to 4), hidden while in member-inspect mode:
            # the full per-member zstats page (exodus/Party.java getZstats) needs
            # the whole panel height for its stat rows plus the complete
            # equipment listings down to the mark/card rows.
            if member_inspect_index is None:
                for i, pm in enumerate(party.members):
                    is_active = (i == party.active_member_index)
                    marker = ">" if is_active else " "

                    # Status abbreviation
                    st_val = getattr(pm.status, "value", str(pm.status))
                    st_abbr = str(st_val)[0].upper()

                    # Status-dependent text color
                    if is_active:
                        member_col = EGA_YELLOW
                    elif st_abbr == "P":
                        member_col = EGA_BRIGHT_GREEN
                    elif st_abbr == "A":
                        member_col = EGA_BRIGHT_RED
                    elif st_abbr == "D":
                        member_col = EGA_DARK_GRAY
                    elif pm.food <= 0:
                        member_col = EGA_WHITE
                    elif pm.hp < 25:
                        member_col = EGA_BRIGHT_RED
                    else:
                        member_col = EGA_WHITE

                    char_name = pm.name.upper()[:8]
                    draw_line(f"{marker}[{i+1}] {char_name:<8} {st_abbr}", member_col)
                    draw_line(
                        f"    H:{pm.hp:<4} M:{pm.mp:<3} F:{pm.food}",
                        EGA_LIGHT_GRAY if not is_active else EGA_YELLOW,
                    )

        # 5. Inspection Section
        eff_inspect = inspect_index if inspect_index is not None else self.inspect_index
        if eff_inspect is not None:
            draw_separator()
            if eff_inspect == -1:
                # Pooled party supplies inspection
                draw_line("-- SUPPLIES --", EGA_BRIGHT_CYAN)
                draw_line(f"GOLD:{party.gold} FOOD:{party.food}", EGA_YELLOW)
                draw_line(f"TORCH DUR: {party.torch_duration}", EGA_WHITE)
                tot_keys = sum(m.keys for m in party.members)
                tot_gems = sum(m.gems for m in party.members)
                tot_torches = sum(m.torches for m in party.members)
                tot_powder = sum(m.powder for m in party.members)
                draw_line(f"KEYS:{tot_keys:<3} GEMS:{tot_gems:<3}", EGA_BRIGHT_GREEN)
                draw_line(f"TORCH:{tot_torches:<2} POWD:{tot_powder:<2}", EGA_BRIGHT_GREEN)
            elif 0 <= eff_inspect < len(party.members):
                target_pm = party.members[eff_inspect]
                # Full zstats inspection (exodus/Party.java:669-715), colors
                # per row kind via inspect_row_color; the identity row already
                # carries the name (Java's first zstats line). Pack 3 inventory
                # cells per line at the 3x resolution so the listing down to
                # the mark/card rows fits, drawn with gapless line spacing.
                ls = f_text.get_linesize()
                for row in inspect_rows(
                    target_pm, self.asset_mgr, per_row=(3 if is_large else 2)
                ):
                    surface.blit(
                        f_text.render(row, False, inspect_row_color(row)),
                        (x_left, curr_y),
                    )
                    curr_y += ls
                    if curr_y > target_rect.bottom:
                        break
        else:
            # When not in detailed inspect mode, show summary inventory if space permits
            if target_rect.bottom - curr_y > line_h * 2 + 10:
                draw_separator()
                tot_keys = sum(m.keys for m in party.members)
                tot_gems = sum(m.gems for m in party.members)
                tot_powder = sum(m.powder for m in party.members)
                draw_line(f"KEYS:{tot_keys} GEMS:{tot_gems} POWD:{tot_powder}", EGA_LIGHT_GRAY)
                if party.torch_duration > 0:
                    draw_line(f"TORCH LIGHT: {party.torch_duration}", EGA_YELLOW)
