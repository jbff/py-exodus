"""Roster management and party formation screen for Ultima III: Exodus."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pygame

from py_exodus.constants import (
    BASE_HEIGHT,
    BASE_WIDTH,
    ArmorType,
    Profession,
    Race,
    Sex,
    Status,
    Transport,
    WeaponType,
)
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.screens.base import BaseScreen
from py_exodus.ui.text_log import (
    EGA_BLACK,
    EGA_BRIGHT_BLUE,
    EGA_BRIGHT_CYAN,
    EGA_BRIGHT_GREEN,
    EGA_BRIGHT_RED,
    EGA_DARK_GRAY,
    EGA_LIGHT_GRAY,
    EGA_WHITE,
    EGA_YELLOW,
    TextLog,
    get_hud_font,
)

if TYPE_CHECKING:
    from py_exodus.assets import AssetManager
    from py_exodus.audio import AudioManager


def get_starter_roster() -> list[Character]:
    """Return an initial pool of classic adventurer recruits."""
    return [
        Character(
            name="Fighter",
            sex=Sex.MALE,
            race=Race.HUMAN,
            profession=Profession.PALADIN,
            strength=20,
            dexterity=15,
            intelligence=10,
            wisdom=15,
            hp=150,
            max_hp=150,
            weapon=WeaponType.SWORD,
            armor=ArmorType.LEATHER,
            food=150,
            gold=50,
        ),
        Character(
            name="Cleric",
            sex=Sex.FEMALE,
            race=Race.BOBIT,
            profession=Profession.CLERIC,
            strength=12,
            dexterity=14,
            intelligence=10,
            wisdom=24,
            hp=100,
            max_hp=100,
            mp=24,
            weapon=WeaponType.MACE,
            armor=ArmorType.CLOTH,
            food=150,
            gold=50,
        ),
        Character(
            name="Wizard",
            sex=Sex.MALE,
            race=Race.ELF,
            profession=Profession.WIZARD,
            strength=10,
            dexterity=14,
            intelligence=25,
            wisdom=11,
            hp=100,
            max_hp=100,
            mp=25,
            weapon=WeaponType.DAGGER,
            armor=ArmorType.CLOTH,
            food=150,
            gold=50,
        ),
        Character(
            name="Thief",
            sex=Sex.FEMALE,
            race=Race.FUZZY,
            profession=Profession.THIEF,
            strength=12,
            dexterity=25,
            intelligence=12,
            wisdom=11,
            hp=120,
            max_hp=120,
            weapon=WeaponType.SLING,
            armor=ArmorType.LEATHER,
            food=150,
            gold=50,
        ),
        Character(
            name="Ranger",
            sex=Sex.MALE,
            race=Race.ELF,
            profession=Profession.RANGER,
            strength=15,
            dexterity=18,
            intelligence=12,
            wisdom=15,
            hp=130,
            max_hp=130,
            mp=15,
            weapon=WeaponType.BOW,
            armor=ArmorType.LEATHER,
            food=150,
            gold=50,
        ),
        Character(
            name="Barbarian",
            sex=Sex.MALE,
            race=Race.DWARF,
            profession=Profession.BARBARIAN,
            strength=25,
            dexterity=12,
            intelligence=8,
            wisdom=8,
            hp=160,
            max_hp=160,
            weapon=WeaponType.AXE,
            armor=ArmorType.LEATHER,
            food=150,
            gold=50,
        ),
    ]


class RosterScreen(BaseScreen):
    """Full-featured keyboard-driven Party and Roster management screen."""

    def __init__(
        self,
        party: Party | None = None,
        roster: list[Character] | None = None,
        asset_mgr: AssetManager | None = None,
        audio: AudioManager | None = None,
        return_screen: BaseScreen | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(return_screen=return_screen, **kwargs)
        self.asset_mgr = asset_mgr
        self.audio = audio

        # Load or initialize active party
        self.party = party or Party(members=[], x=44, y=20, food=400, gold=200)

        # Load or initialize roster
        if roster is not None:
            self.roster = roster
        else:
            self.roster = self._load_initial_roster()

        self.selected_roster_idx: int = 0
        self.roster_scroll_offset: int = 0
        self.selected_party_idx: int = 0
        self.focus_panel: str = "roster"  # "roster" or "party"

        self.text_log = TextLog(max_lines=3, wrap_width=45)
        self.text_log.add_message("Party Formation: [A]dd, [R]emove, [C]reate, [Q]uick, [E]mbark")

        # Creation wizard state
        self._creating_char: bool = False
        self._new_char_data: dict[str, Any] = {}

    def _load_initial_roster(self) -> list[Character]:
        """Load characters from roster file or provide starter pool."""
        from py_exodus.save_system import SaveSystem

        candidates = [
            Path("saves/roster.json"),
            Path("assets/data/roster.ult"),
            Path("src/main/resources/assets/data/roster.ult"),
        ]
        for c in candidates:
            if c.exists():
                try:
                    loaded = SaveSystem.load_roster(c)
                    valid = [char for char in loaded if char.name.strip()]
                    if valid:
                        return valid
                except Exception:
                    pass

        return get_starter_roster()

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return

        # If text_log prompt is active (e.g. during character creation)
        if self.text_log.is_waiting_for_input:
            self.text_log.handle_event(event)
            return

        # Navigation
        if event.key in (pygame.K_UP, pygame.K_w):
            if self.focus_panel == "roster":
                if self.roster:
                    self.selected_roster_idx = (self.selected_roster_idx - 1) % len(self.roster)
            else:
                self.selected_party_idx = (self.selected_party_idx - 1) % 4
        elif event.key in (pygame.K_DOWN, pygame.K_s):
            if self.focus_panel == "roster":
                if self.roster:
                    self.selected_roster_idx = (self.selected_roster_idx + 1) % len(self.roster)
            else:
                self.selected_party_idx = (self.selected_party_idx + 1) % 4
        elif event.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_TAB):
            self.focus_panel = "party" if self.focus_panel == "roster" else "roster"

        # Action shortcuts
        elif event.key == pygame.K_a:  # Add to party
            self._add_selected_to_party()
        elif event.key == pygame.K_r:  # Remove from party
            self._remove_from_party()
        elif event.key == pygame.K_q:  # Quick Start / Classic balanced party
            self._quick_start_party()
        elif event.key == pygame.K_c:  # Create new character
            self._start_create_character()
        elif event.key == pygame.K_d:  # Delete selected character from roster
            self._delete_selected_roster()
        elif event.key in (pygame.K_e, pygame.K_RETURN, pygame.K_KP_ENTER):  # Embark
            self._embark()
        elif event.key == pygame.K_ESCAPE:  # Exit to start screen
            self.exit_screen()

    def _add_selected_to_party(self) -> None:
        """Add highlighted roster member to first available party slot."""
        if not self.roster:
            self.text_log.add_message("Roster is empty! Press [C] to create a character.")
            return

        if len(self.party.members) >= 4:
            self.text_log.add_message("Party is full! Max 4 members allowed.")
            return

        char = self.roster[self.selected_roster_idx]
        # Check if already in party
        if any(m.name.upper() == char.name.upper() for m in self.party.members):
            self.text_log.add_message(f"{char.name} is already in the party!")
            return

        self.party.add_member(char)
        if self.audio is not None:
            self.audio.play_sfx("trigger")
        self.text_log.add_message(f"Added {char.name} to party! ({len(self.party.members)}/4)")

    def _remove_from_party(self) -> None:
        """Remove member from party."""
        if not self.party.members:
            self.text_log.add_message("Party has no members to remove.")
            return

        target_idx = self.selected_party_idx if self.focus_panel == "party" else len(self.party.members) - 1
        if 0 <= target_idx < len(self.party.members):
            removed = self.party.members.pop(target_idx)
            if self.audio is not None:
                self.audio.play_sfx("trigger")
            self.text_log.add_message(f"Removed {removed.name} from party. ({len(self.party.members)}/4)")
        else:
            self.text_log.add_message("No member at selected slot.")

    def _quick_start_party(self) -> None:
        """Load standard balanced party for immediate embarking."""
        from py_exodus.screens.start import create_default_starter_party

        starter = create_default_starter_party()
        self.party = starter
        if self.audio is not None:
            self.audio.play_sfx("trigger")
        self.text_log.add_message("Quick Party loaded: Fighter, Cleric, Wizard, Thief!")

    def _delete_selected_roster(self) -> None:
        """Delete highlighted recruit from roster."""
        if not self.roster:
            return
        removed = self.roster.pop(self.selected_roster_idx)
        if self.selected_roster_idx >= len(self.roster) and self.roster:
            self.selected_roster_idx = len(self.roster) - 1
        self.text_log.add_message(f"Deleted {removed.name} from roster.")

    def _start_create_character(self) -> None:
        """Initiate interactive text prompt sequence to create a character."""
        self._new_char_data = {}

        def _step_profession(prof_str: str) -> None:
            prof_map = {
                "F": Profession.FIGHTER,
                "C": Profession.CLERIC,
                "W": Profession.WIZARD,
                "T": Profession.THIEF,
                "P": Profession.PALADIN,
                "B": Profession.BARBARIAN,
                "R": Profession.RANGER,
                "L": Profession.LARK,
                "I": Profession.ILLUSIONIST,
                "D": Profession.DRUID,
                "A": Profession.ALCHEMIST,
            }
            code = prof_str.strip().upper()[:1]
            prof = prof_map.get(code, Profession.FIGHTER)
            self._new_char_data["prof"] = prof

            # Assemble character
            name = self._new_char_data["name"]
            sex = self._new_char_data["sex"]
            race = self._new_char_data["race"]
            prof = self._new_char_data["prof"]

            # Set starting stats
            base_str = 15
            base_dex = 15
            base_int = 10
            base_wis = 10
            hp = 150
            mp = 0
            wpn = WeaponType.DAGGER
            arm = ArmorType.CLOTH

            if prof in (Profession.FIGHTER, Profession.PALADIN, Profession.BARBARIAN):
                base_str = 20
                wpn = WeaponType.SWORD
                arm = ArmorType.LEATHER
            elif prof in (Profession.WIZARD, Profession.ILLUSIONIST, Profession.ALCHEMIST):
                base_int = 25
                mp = 25
            elif prof in (Profession.CLERIC, Profession.DRUID):
                base_wis = 25
                mp = 25
                wpn = WeaponType.MACE
            elif prof in (Profession.THIEF, Profession.RANGER, Profession.LARK):
                base_dex = 22
                wpn = WeaponType.BOW if prof == Profession.RANGER else WeaponType.SLING
                arm = ArmorType.LEATHER

            new_char = Character(
                name=name,
                sex=sex,
                race=race,
                profession=prof,
                strength=base_str,
                dexterity=base_dex,
                intelligence=base_int,
                wisdom=base_wis,
                hp=hp,
                max_hp=hp,
                mp=mp,
                weapon=wpn,
                armor=arm,
                food=150,
                gold=50,
            )
            self.roster.append(new_char)
            self.selected_roster_idx = len(self.roster) - 1
            self.text_log.add_message(f"Created {name} ({prof.name})! Added to roster.")

        def _step_race(race_str: str) -> None:
            race_map = {
                "H": Race.HUMAN,
                "E": Race.ELF,
                "D": Race.DWARF,
                "B": Race.BOBIT,
                "F": Race.FUZZY,
            }
            code = race_str.strip().upper()[:1]
            self._new_char_data["race"] = race_map.get(code, Race.HUMAN)
            self.text_log.prompt("Class: [F]ight [C]leric [W]iz [T]hief [P]al [R]ang [B]arb:", _step_profession, single_char=True)

        def _step_sex(sex_str: str) -> None:
            sex = Sex.FEMALE if sex_str.strip().upper().startswith("F") else Sex.MALE
            self._new_char_data["sex"] = sex
            self.text_log.prompt("Race: [H]uman [E]lf [D]warf [B]obit [F]uzzy:", _step_race, single_char=True)

        def _step_name(name_str: str) -> None:
            name = name_str.strip() or f"Hero{len(self.roster)+1}"
            self._new_char_data["name"] = name[:8]
            self.text_log.prompt("Sex: [M]ale or [F]emale:", _step_sex, single_char=True)

        self.text_log.prompt("Character Name (up to 8 chars):", _step_name)

    def _embark(self) -> None:
        """Validate party and launch overworld adventure."""
        if not self.party.members:
            self.text_log.add_message("Cannot embark! Form a party with at least 1 member.")
            return

        # Save roster and party
        try:
            from py_exodus.save_system import SaveSystem

            Path("saves").mkdir(parents=True, exist_ok=True)
            SaveSystem.save_game(self.party, "saves/party.json")
            SaveSystem.save_roster(self.roster, "saves/roster.json")
        except Exception:
            pass

        from py_exodus.screens.overworld import OverworldScreen

        overworld = OverworldScreen(
            party=self.party,
            asset_mgr=self.asset_mgr,
            audio=self.audio,
            return_screen=self,
            manager=self.manager,
        )
        if self.manager is not None:
            self.manager.set_screen(overworld)
        else:
            self.next_screen = overworld
            self.is_finished = True

    def render(self, surface: pygame.Surface) -> None:
        surface.fill(EGA_BLACK)
        w, h = surface.get_width(), surface.get_height()
        scale = 3 if w >= 640 else 1

        f_title = get_hud_font(size=14 * scale, font_name="ultima.ttf")
        f_hud = get_hud_font(size=11 * scale)
        f_small = get_hud_font(size=10 * scale)

        # 1. Title Banner
        title = "PARTY FORMATION & ROSTER"
        title_surf = f_title.render(title, True, EGA_YELLOW)
        surface.blit(title_surf, ((w - title_surf.get_width()) // 2, 4 * scale))

        # 2. Party Box (Left)
        p_rect = pygame.Rect(6 * scale, 22 * scale, 144 * scale, 122 * scale)
        pygame.draw.rect(surface, (15, 15, 30), p_rect)
        border_col = EGA_YELLOW if self.focus_panel == "party" else EGA_DARK_GRAY
        pygame.draw.rect(surface, border_col, p_rect, max(1, scale))

        p_header = f"PARTY ({len(self.party.members)}/4)"
        surface.blit(f_hud.render(p_header, False, EGA_BRIGHT_CYAN), (10 * scale, 26 * scale))

        for slot in range(4):
            slot_y = (42 + slot * 24) * scale
            is_sel = (self.focus_panel == "party" and self.selected_party_idx == slot)
            marker = ">" if is_sel else " "

            if slot < len(self.party.members):
                m = self.party.members[slot]
                p_name = m.name.upper()[:7]
                prof_name = getattr(m.profession, "name", str(m.profession))[:5]
                col = EGA_YELLOW if is_sel else EGA_WHITE
                surface.blit(f_small.render(f"{marker}[{slot+1}] {p_name} ({prof_name})", False, col), (10 * scale, slot_y))
                surface.blit(f_small.render(f"    HP:{m.hp} MP:{m.mp} FOOD:{m.food}", False, EGA_LIGHT_GRAY), (10 * scale, slot_y + 11 * scale))
            else:
                col = EGA_YELLOW if is_sel else EGA_DARK_GRAY
                surface.blit(f_small.render(f"{marker}[{slot+1}] <EMPTY SLOT>", False, col), (10 * scale, slot_y + 4 * scale))

        # 3. Roster Box (Right)
        r_rect = pygame.Rect(154 * scale, 22 * scale, (w - 160 * scale), 122 * scale)
        pygame.draw.rect(surface, (15, 15, 30), r_rect)
        r_border = EGA_YELLOW if self.focus_panel == "roster" else EGA_DARK_GRAY
        pygame.draw.rect(surface, r_border, r_rect, max(1, scale))

        r_header = f"ROSTER ({len(self.roster)} RECRUITS)"
        surface.blit(f_hud.render(r_header, False, EGA_BRIGHT_CYAN), (158 * scale, 26 * scale))

        # Show up to 5 recruits at a time
        max_visible = 5
        start_idx = max(0, min(self.selected_roster_idx - max_visible // 2, max(0, len(self.roster) - max_visible)))
        visible_recs = self.roster[start_idx : start_idx + max_visible]

        for i, rec in enumerate(visible_recs):
            actual_idx = start_idx + i
            is_sel = (self.focus_panel == "roster" and self.selected_roster_idx == actual_idx)
            marker = ">" if is_sel else " "
            col = EGA_YELLOW if is_sel else EGA_WHITE
            row_y = (44 + i * 18) * scale

            name = rec.name.upper()[:8]
            prof = getattr(rec.profession, "name", str(rec.profession))[:4]
            race = getattr(rec.race, "name", str(rec.race))[:3]
            surface.blit(f_small.render(f"{marker}{actual_idx+1}:{name:<8} {prof} {race}", False, col), (158 * scale, row_y))
            surface.blit(f_small.render(f"   H:{rec.hp:<3} S:{rec.str:<2} D:{rec.dex:<2} I:{rec.int:<2}", False, EGA_LIGHT_GRAY), (158 * scale, row_y + 9 * scale))

        if not self.roster:
            surface.blit(f_small.render("No recruits in roster.", False, EGA_DARK_GRAY), (162 * scale, 50 * scale))
            surface.blit(f_small.render("Press [C] to create one!", False, EGA_BRIGHT_GREEN), (162 * scale, 65 * scale))

        # 4. Command Bar
        cmd_y = 146 * scale
        c1 = "[A] Add to Party   [R] Remove from Party"
        c2 = "[C] Create Hero    [Q] Quick 4-Hero Party"
        c3 = "[E/ENTER] Embark!  [ESC] Back to Title"
        surface.blit(f_small.render(c1, False, EGA_BRIGHT_GREEN), (10 * scale, cmd_y))
        surface.blit(f_small.render(c2, False, EGA_BRIGHT_CYAN), (10 * scale, cmd_y + 11 * scale))
        surface.blit(f_small.render(c3, False, EGA_YELLOW), (10 * scale, cmd_y + 22 * scale))

        # 5. Bottom Interactive Text Log
        self.text_log.render(
            surface,
            rect=pygame.Rect(6 * scale, 176 * scale, w - 12 * scale, h - 178 * scale),
            draw_border=True,
            font=f_small,
        )
