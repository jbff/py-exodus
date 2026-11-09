"""Party Stats Panel and Character Inspection Sidebar for Ultima III HUD."""
from __future__ import annotations

import pygame

from py_exodus.constants import Transport
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


def _inventory_rows(cells: list[str], prefix: str, per_row: int = 2) -> list[str]:
    """Rows listing a full weapon/armor inventory, 2 cells per row.

    Java zstats lists every non-zero inventory entry (exodus/Party.java:673-697
    pairs two ArmorType/WeaponType names per line, then appends the EXOTIC
    entry), so nothing here is truncated.
    """
    rows: list[str] = []
    if not cells:
        return rows
    rows.append(f"{prefix}: " + "  ".join(cells[:per_row]))
    for i in range(per_row, len(cells), per_row):
        rows.append("   " + "  ".join(cells[i : i + per_row]))
    return rows


def inspect_rows(pm: object) -> list[str]:
    """Zstats inspection rows for one member, in Java getZstats order
    (exodus/Party.java:669-715): the race/sex/class/status identity line,
    HEALTH/MAXHEALTH, MANA/LV, the STR/DEX/INT/WIS pairs with EXP, the
    readied weapon and worn armor, torch/gem/key/powder counts, per-member
    GOLD and FOOD, then the full armor and weapon inventory listings and the
    mark/card rows. The name header is drawn separately by StatsPanel.
    """
    race = getattr(getattr(pm, "race", None), "name", "")
    sex = getattr(getattr(pm, "sex", None), "value", "")
    prof = getattr(getattr(pm, "profession", None), "name", "")
    status = getattr(pm.status, "value", str(pm.status))
    st = status[0].upper() if status else "?"
    rows = [
        f"{race} {sex} {prof} ST:{st}",
        f"HP:{pm.hp}/{pm.max_hp}",
        f"MANA:{pm.mp} LV:{pm.level}",
        f"STR:{pm.str} DEX:{pm.dex}",
        f"INT:{pm.int} WIS:{pm.wis}",
        f"EXP:{pm.exp}",
        f"WPN: {getattr(pm.weapon, 'value', str(pm.weapon))}",
        f"ARM: {getattr(pm.armor, 'value', str(pm.armor))}",
        f"TORCH:{pm.torches} GEMS:{pm.gems}",
        f"KEYS:{pm.keys} POWD:{pm.powder}",
        f"GOLD:{pm.gold} FOOD:{pm.food}",
    ]
    armor_cells = [
        f"{getattr(at, 'name', at)}({cnt})" for at, cnt in pm.armors.items() if cnt > 0
    ]
    rows.extend(_inventory_rows(armor_cells, "A"))
    weapon_cells = [
        f"{getattr(wt, 'name', wt)}({cnt})" for wt, cnt in pm.weapons.items() if cnt > 0
    ]
    rows.extend(_inventory_rows(weapon_cells, "W"))
    rows.extend(mark_and_card_rows(pm))
    return rows


def inspect_row_color(row: str) -> tuple[int, int, int]:
    """Draw color for an inspect row: inventory gray, supplies/mark rows green."""
    if row.startswith(("W:", "A:", " ")):
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
    ) -> None:
        self.font = font
        self.small_font = small_font
        self.inspect_index: int | None = inspect_index

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

        # 4. Party Members (up to 4)
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

        # 4. Inspection Section
        eff_inspect = inspect_index if inspect_index is not None else self.inspect_index
        if eff_inspect is not None:
            draw_separator()
            if 0 <= eff_inspect < len(party.members):
                target_pm = party.members[eff_inspect]
                draw_line(f"-- {target_pm.name.upper()} --", EGA_BRIGHT_CYAN)
                # Full zstats inspection (exodus/Party.java:669-715); colors
                # per row kind via inspect_row_color.
                for row in inspect_rows(target_pm):
                    draw_line(row, inspect_row_color(row))
                    if curr_y > target_rect.bottom:
                        break
            elif eff_inspect == -1:
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
