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


# Roster capacity: objects/Roster.java holds exactly 20 CharacterRecord slots.
ROSTER_SLOTS = 20
# Creation allocation rules (ManagePartyScreen.java:355-358,176-180):
# sliders 5..25 per stat, total across the four stats at most 50.
CREATION_MIN_STAT = 5
CREATION_MAX_STAT = 25
CREATION_MAX_POINTS = 50


def get_starter_roster() -> list[Character]:
    """Return an initial pool of classic adventurer recruits.

    Starting MP is original-rules parity (user-directed deviation): casters
    carry spell points equal to the max from the CharacterRecord.getMaxMana
    formula (SaveGame.java:340-376) — WIZARD/CLERIC whole governing stat,
    others half — and non-casters 0. Java's roster writer itself never seeds
    mana, hence the explicit fill-in instead of hardcoded values.
    """
    recruits = [
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
    for rec in recruits:
        # Original-rules starting MP (SaveGame.java:340-376 getMaxMana).
        rec.mp = rec.compute_max_mp()
    return recruits


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
        # Load or initialize active party.
        # Per-member model (Task 4): gold and food live on each Character
        # record — there is no party-level seed pool.
        # Default new-game position (45, 19): Java SaveGame.java:164-169
        # seeds partyX/partyY to (45, 19) — the grass tile just south of the
        # Castle British entrance portal at (45, 18).
        self.party = party or Party(members=[], x=45, y=19)

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
        # Mouse wheel scrolls the shared text log back through history
        # (Java LogScrollPane affordance).
        if event.type == pygame.MOUSEWHEEL:
            self.text_log.handle_wheel(event)
            return

        if event.type != pygame.KEYDOWN:
            return

        # If text_log prompt is active (e.g. during character creation)
        if self.text_log.is_waiting_for_input:
            self.text_log.handle_event(event)
            return

        # PageUp/PageDown always scroll the text log back (arrow keys stay
        # roster navigation keys).
        if self.text_log.handle_scroll_key(event.key):
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
        """Remove member from party, returning them to a roster slot.

        Java truth: ``exodus/ManagePartyScreen.java:355-367`` — the removed
        party character is written back into the roster: a roster slot with
        the same name is replaced with the party-state version; otherwise the
        first empty slot takes the member. When the registry has no room
        (``objects/Roster.java`` holds 20 slots) the removal is refused and
        the member stays in the party.
        """
        if not self.party.members:
            self.text_log.add_message("Party has no members to remove.")
            return

        target_idx = self.selected_party_idx if self.focus_panel == "party" else len(self.party.members) - 1
        if not (0 <= target_idx < len(self.party.members)):
            self.text_log.add_message("No member at selected slot.")
            return

        member = self.party.members[target_idx].character

        existing_slot = next(
            (i for i, c in enumerate(self.roster) if c.name.upper() == member.name.upper()),
            None,
        )
        if existing_slot is None and len(self.roster) >= ROSTER_SLOTS:
            self.text_log.add_message("No room in the roster for that adventurer!")
            if self.audio is not None:
                self.audio.play_sfx("negative")
            return

        self.party.members.pop(target_idx)
        if existing_slot is not None:
            self.roster[existing_slot] = member
        else:
            self.roster.append(member)
            self.selected_roster_idx = len(self.roster) - 1

        if self.audio is not None:
            self.audio.play_sfx("trigger")
        self.text_log.add_message(
            f"Removed {member.name} from party. ({len(self.party.members)}/4)"
        )

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
        """Initiate interactive text prompt sequence to create a character.

        Java truth: ``exodus/ManagePartyScreen.java:165-199,355-367`` — the
        stat sliders allocate each of STR/DEX/INT/WIS in 5..25, the total may
        not exceed 50 (over-budget apply is refused, nothing is committed),
        the name field accepts up to 16 characters, and a created character
        starts with health/food/gold = 150 and NO weapon or armor. Stat
        validation is delegated to ``Character.validate_creation``.
        """
        self._new_char_data = {}
        stat_names = ["Strength", "Dexterity", "Intelligence", "Wisdom"]

        def _start_stat_allocation() -> None:
            self._new_char_data["stats"] = [0, 0, 0, 0]
            self._new_char_data["stat_step"] = 0
            self.text_log.add_message("Allocate stats: each 5-25, total must not exceed 50.")
            _prompt_next_stat()

        def _prompt_next_stat() -> None:
            step = self._new_char_data["stat_step"]
            self.text_log.prompt(
                f"{stat_names[step]} (5-25):",
                _step_stat,
                single_char=False,
            )

        def _step_stat(raw: str) -> None:
            step = self._new_char_data["stat_step"]
            try:
                value = int(raw.strip())
            except ValueError:
                self.text_log.add_message(f"{stat_names[step]}: enter a number 5-25.")
                _prompt_next_stat()
                return
            if not (CREATION_MIN_STAT <= value <= CREATION_MAX_STAT):
                self.text_log.add_message(f"{stat_names[step]} ({value}) must be 5-25.")
                _prompt_next_stat()
                return
            self._new_char_data["stats"][step] = value
            self._new_char_data["stat_step"] = step + 1
            if self._new_char_data["stat_step"] < len(stat_names):
                _prompt_next_stat()
                return
            _assemble_character()

        def _assemble_character() -> None:
            name = self._new_char_data["name"]
            sex = self._new_char_data["sex"]
            race = self._new_char_data["race"]
            prof = self._new_char_data["prof"]
            st, dx, in_, wi = self._new_char_data["stats"]

            # 5-25 per stat and total <= 50 (ManagePartyScreen.java:176-180),
            # via the shared validator wired here.
            valid, err = Character.validate_creation(
                race=race,
                profession=prof,
                strength=st,
                dexterity=dx,
                intelligence=in_,
                wisdom=wi,
                max_points=CREATION_MAX_POINTS,
                min_stat=CREATION_MIN_STAT,
                max_stat=CREATION_MAX_STAT,
            )
            if not valid:
                self.text_log.add_message(err)
                # Java refuses the apply and keeps the allocation UI open:
                # restart the stat prompts with nothing committed.
                _start_stat_allocation()
                return

            if len(self.roster) >= ROSTER_SLOTS:
                self.text_log.add_message("The roster is full (20 adventurers)!")
                return

            # Starting record: health/food/gold = 150, portrait index, and
            # NO weapon or armor (ManagePartyScreen.java:185-192). Max MP is
            # derived from profession/stats, not chosen here.
            new_char = Character(
                name=name,
                sex=sex,
                race=race,
                profession=prof,
                strength=st,
                dexterity=dx,
                intelligence=in_,
                wisdom=wi,
                hp=150,
                max_hp=150,
                food=150,
                gold=150,
                portrait_index=self._new_char_data["portrait"],
            )
            # Starting spell points: original-rules parity (user-directed
            # deviation). Java's own creator (ManagePartyScreen.java) never
            # touches mana — created casters ticked up to 1 MP via the first
            # endTurn meal regeneration instead (SaveGame.java:387 clamps
            # mana to getMaxMana()). The C64 original starts a caster with
            # spell points equal to the max computed by the same formula as
            # CharacterRecord.getMaxMana (SaveGame.java:340-376), so a
            # casting profession starts full and a non-caster (capability 0)
            # starts at 0.
            new_char.mp = new_char.compute_max_mp()
            self.roster.append(new_char)
            self.selected_roster_idx = len(self.roster) - 1
            self.text_log.add_message(f"Created {name} ({prof.name})! Added to roster.")

        def _step_portrait(raw: str) -> None:
            raw = raw.strip()
            if not raw:
                idx = 43
            else:
                try:
                    idx = int(raw)
                except ValueError:
                    idx = 43
            idx = max(0, min(43, idx))
            self._new_char_data["portrait"] = idx
            _start_stat_allocation()

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
            self._new_char_data["prof"] = prof_map.get(code, Profession.FIGHTER)
            self.text_log.prompt("Portrait (0-43, ENTER for 43):", _step_portrait, single_char=False)

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
            # nameField.setMaxLength(16) (ManagePartyScreen.java:389); the
            # apply listener refuses an empty name.
            name = name_str.strip()[:16]
            if not name:
                name = f"Hero{len(self.roster) + 1}"
            self._new_char_data["name"] = name
            self.text_log.prompt("Sex: [M]ale or [F]emale:", _step_sex, single_char=True)

        self.text_log.prompt("Character Name (up to 16 chars):", _step_name)

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
