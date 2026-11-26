"""Roster management and party formation screen for Ultima III: Exodus."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pygame

from py_exodus.constants import (
    ArmorType,
    Profession,
    Race,
    Sex,
    WeaponType,
)
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.screens.base import BaseScreen
from py_exodus.ui.text_log import TextLog

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
# Name length: LairWare UltimaMacIF.c:2430-2432,2492-2496 keeps 12 letters.
CREATION_MAX_NAME = 12


def same_record(a: Any, b: Any) -> bool:
    """True when ``a`` and ``b`` are the same roster record.

    LairWare names a record by its roster slot, never by its name: the party
    stores slot numbers (UltimaNew.c:204-210) and Terminate clears the slot
    picked (UltimaNew.c:60-79, 90-101), so two characters may share a name
    (user ruling Q4). Party members wrap the roster's own objects; a member
    loaded from a save is matched by its stored slot."""
    a = getattr(a, "character", a)
    b = getattr(b, "character", b)
    if a is b:
        return True
    slot = getattr(a, "roster_slot", 0)
    return bool(slot) and slot == getattr(b, "roster_slot", 0)


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
        # Default new-game position: Java seeds (45, 19) (SaveGame.java:164-169)
        # — the grass tile just south of the Castle British entrance portal at
        # (45, 18). USER-DIRECTED NIT (2026-11-15): fresh Journeys spawn one
        # south + one west of the Java default, at (44, 20), so this path
        # constructs Party() with no x/y override and inherits that default.
        if party is not None and party.members and party.is_party_dead():
            party = None
        self.party = party or Party(members=[])
        # LairWare FormPartyDialog (UltimaNew.c:128-134): while a party
        # exists ("(Party in use)") no other can be formed, and its members
        # can't be swapped; it must be dispersed first (user ruling Q2). A
        # party handed to this screen is that existing party; one built here
        # is a new one being chosen.
        self.party_formed: bool = bool(self.party.members)

        # Load or initialize roster
        if roster is not None:
            self.roster = roster
        else:
            self.roster = self._load_initial_roster()
        self._number_roster()
        self._link_unnumbered_members()

        self.selected_roster_idx: int = 0
        self.roster_scroll_offset: int = 0
        self.selected_party_idx: int = 0
        self.focus_panel: str = "roster"  # "roster" or "party"

        # No wrapping: the screen shows the newest message whole on one line.
        self.text_log = TextLog(max_lines=3)
        if self.party_formed:
            self.text_log.add_message(
                "A party is in use: Journey Onward resumes it, [X] disperses it."
            )
        else:
            self.text_log.add_message("Form a party of up to four, then Enter to embark.")

        # Creation wizard state: the step (0 name .. 4 stats, None when not
        # creating), the highlighted choice of a choosing step, the stat the
        # arrows adjust and the last note the wizard gave.
        self._creating_char: bool = False
        self._new_char_data: dict[str, Any] = {}
        self._create_step: int | None = None
        self._create_cursor: int = 0
        self._stat_sel: int = 0
        self._create_note: str = ""

    def _load_initial_roster(self) -> list[Character]:
        """Load characters from the roster file, else start empty.

        Java truth: ManagePartyScreen.java:85-99 seeds the registry from
        roster.sav and every record without a name shows <empty> — a fresh
        install has an EMPTY roster (Java ships a blank 20-slot roster file;
        here that ships as an empty JSON roster, assets/data/roster.json,
        same semantics). Java ships no starter pool, so neither does this
        screen: new players create characters with [C].
        """
        from py_exodus.save_system import SaveSystem

        candidates = [
            Path("saves/roster.json"),
            Path("assets/data/roster.json"),
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

        return []

    def _number_roster(self) -> None:
        """Give every roster record its own slot 1..20 (LairWare Player[1..20]).
        Records from saves made before slots existed, or that clash, take the
        lowest free slot in roster order."""
        used: set[int] = set()
        for char in self.roster:
            slot = getattr(char, "roster_slot", 0)
            if not (1 <= slot <= ROSTER_SLOTS) or slot in used:
                slot = next(s for s in range(1, ROSTER_SLOTS * 2 + 1) if s not in used)
                char.roster_slot = slot
            used.add(slot)

    def _link_unnumbered_members(self) -> None:
        """A party saved before roster slots existed names its members only:
        each unnumbered member takes the slot of the one roster record of its
        name not already linked (save compatibility for user ruling Q4)."""
        taken = {m.character.roster_slot for m in self.party.members if m.character.roster_slot}
        for m in self.party.members:
            char = m.character
            if char.roster_slot or any(c is char for c in self.roster):
                continue
            match = [
                c for c in self.roster
                if c.name.upper() == char.name.upper() and c.roster_slot not in taken
            ]
            if len(match) == 1:
                char.roster_slot = match[0].roster_slot
                taken.add(char.roster_slot)

    def _free_slot(self) -> int:
        """The lowest roster slot no record holds."""
        used = {getattr(c, "roster_slot", 0) for c in self.roster}
        return next(s for s in range(1, ROSTER_SLOTS * 2 + 1) if s not in used)

    def handle_event(self, event: pygame.event.Event) -> None:
        # Mouse wheel scrolls the shared text log back through history
        # (Java LogScrollPane affordance).
        if event.type == pygame.MOUSEWHEEL:
            self.text_log.handle_wheel(event)
            return

        if event.type != pygame.KEYDOWN:
            return

        # The creation steps take the arrows, Enter and Esc first; letters,
        # digits and the name still go to the step's prompt as before.
        if self._create_step is not None and self._handle_create_key(event):
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
        elif event.key == pygame.K_p:  # Save party + roster (Java Save button)
            self._save_party_formations()
        elif event.key == pygame.K_c:  # Create new character
            self._start_create_character()
        elif event.key == pygame.K_d:  # Delete selected character from roster
            self._delete_selected_roster()
        elif event.key == pygame.K_x:  # Disperse the party (LairWare D)
            self._disperse_party()
        elif event.key in (pygame.K_e, pygame.K_RETURN, pygame.K_KP_ENTER):  # Embark
            self._embark()
        elif event.key == pygame.K_ESCAPE:  # Exit to start screen
            self.exit_screen()
        self._follow_selection()

    def _follow_selection(self) -> None:
        """Scroll the 20-row list so the selected row is among the ten shown."""
        from py_exodus.ui.roster_view import VISIBLE_ROWS, scroll_offset

        if self.roster:
            self.selected_roster_idx = max(0, min(self.selected_roster_idx, len(self.roster) - 1))
        self.roster_scroll_offset = scroll_offset(
            self.selected_roster_idx, self.roster_scroll_offset, VISIBLE_ROWS, ROSTER_SLOTS
        )

    def _refuse_party_in_use(self) -> bool:
        """LairWare's "(Party in use)" (UltimaNew.c:128-134): True, with the
        message, when a party exists and so none can be formed or changed."""
        if not self.party_formed:
            return False
        self.text_log.add_message("Party in use! Disperse it first with [X].")
        if self.audio is not None:
            self.audio.play_sfx("negative")
        return True

    def _disperse_party(self) -> None:
        """LairWare DisperseParty (UltimaMain.c:724-745): the party is broken
        up and its record cleared, "(Dispersed!)"; with none, "(No one
        there)". LairWare's members are the roster records themselves, so
        what they gained stays on the roster: each member is written back
        into its own slot (a member with no record takes a free slot; with
        none free nothing is dispersed). The saved party is removed, so
        Journey Onward has nothing to resume (user ruling Q2)."""
        if not self.party_formed:
            self.text_log.add_message("No party to disperse.")
            return
        members = [m.character for m in self.party.members]
        homeless = [c for c in members if not any(same_record(r, c) for r in self.roster)]
        if len(self.roster) + len(homeless) > ROSTER_SLOTS:
            self.text_log.add_message("No room in the roster for that adventurer!")
            return
        for char in members:
            idx = next((i for i, r in enumerate(self.roster) if same_record(r, char)), None)
            if idx is None:
                char.roster_slot = self._free_slot()
                self.roster.append(char)
            else:
                self.roster[idx] = char
        self.party = Party(members=[])
        self.party_formed = False
        self.selected_party_idx = 0
        try:
            from py_exodus.save_system import SaveSystem

            Path("saves").mkdir(parents=True, exist_ok=True)
            SaveSystem.save_roster(self.roster, "saves/roster.json")
            Path("saves/party.json").unlink(missing_ok=True)
        except Exception:
            pass
        if self.audio is not None:
            self.audio.play_sfx("trigger")
        self.text_log.add_message("Party dispersed!")

    def _add_selected_to_party(self) -> None:
        """Add highlighted roster member to first available party slot."""
        if self._refuse_party_in_use():
            return
        if not self.roster:
            self.text_log.add_message("Roster is empty! Press [C] to create a character.")
            return

        if len(self.party.members) >= 4:
            self.text_log.add_message("Party is full! Max 4 members allowed.")
            return

        char = self.roster[self.selected_roster_idx]
        # The same record twice is refused (LairWare FormPartyDialog
        # `sel[temp] == sel[i]`, UltimaNew.c:247-250); a same-named other
        # record may join (user ruling Q4).
        if any(same_record(m, char) for m in self.party.members):
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
        if self._refuse_party_in_use():
            return
        if not self.party.members:
            self.text_log.add_message("Party has no members to remove.")
            return

        target_idx = self.selected_party_idx if self.focus_panel == "party" else len(self.party.members) - 1
        if not (0 <= target_idx < len(self.party.members)):
            self.text_log.add_message("No member at selected slot.")
            return

        member = self.party.members[target_idx].character

        existing_slot = next(
            (i for i, c in enumerate(self.roster) if same_record(c, member)),
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
            member.roster_slot = self._free_slot()
            self.roster.append(member)
            self.selected_roster_idx = len(self.roster) - 1

        if self.audio is not None:
            self.audio.play_sfx("trigger")
        self.text_log.add_message(
            f"Removed {member.name} from party. ({len(self.party.members)}/4)"
        )

    def _write_party_saves(self) -> None:
        """Write both save records (Java ManagePartyScreen.java:262-293 Save
        button): the full roster to saves/roster.json (Java's roster.sav,
        every slot) and the formed party to saves/party.json (Java writes the
        partyFormation slots into saveGame.players[0..3], counts them into
        numberInParty, then saveGame.write(party.sav); this party carries only
        its filled slots, in slot order). Java's loader seeds a fresh record
        with transport FOOT and the (45,19) start tile (SaveGame.java:164-169),
        which the Party defaults already carry."""
        from py_exodus.save_system import SaveSystem

        Path("saves").mkdir(parents=True, exist_ok=True)
        # A party in use is already saved, with its world; writing it again
        # from here would drop the world (user ruling Q2).
        if not self.party_formed:
            SaveSystem.save_game(self.party, "saves/party.json")
        SaveSystem.save_roster(self.roster, "saves/roster.json")

    def _save_party_formations(self) -> None:
        """Save the formed party and roster, then return to the title screen.

        Java truth: ManagePartyScreen.java:262-293 — the Save button writes
        BOTH records and returns to the start screen; saving requires no
        embark, so a formed party survives quitting to the title.
        """
        try:
            self._write_party_saves()
            self.text_log.add_message("Party and roster saved.")
        except Exception:
            self.text_log.add_message("Save failed!")
        if self.audio is not None:
            self.audio.play_sfx("trigger")
        # Java's Save button returns to returnScreen either way.
        self.exit_screen()

    def _delete_selected_roster(self) -> None:
        """Delete highlighted recruit from roster, behind a Y/N confirm.

        USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): roster delete confirms and refuses in-party characters (GBC intro.c:1455-1490)
        """
        if not self.roster:
            return
        char = self.roster[self.selected_roster_idx]

        # GBC intro.c:1455-1490 terminatecharacter / LairWare
        # TerminateCharacterDialog (UltimaNew.c:74-75): a record in the party
        # is never deletable; a same-named other record is (user ruling Q4).
        if any(same_record(m, char) for m in self.party.members):
            self.text_log.add_message("That character is in a party!")
            return

        def _on_confirm(answer: str) -> None:
            if answer.strip().upper() != "Y":
                return  # N or any other key: nothing is deleted
            # The slot picked, never another of the same name (LairWare
            # `Player[rosNum][0] = 0`, UltimaNew.c:92).
            idx = next((i for i, c in enumerate(self.roster) if c is char), None)
            if idx is None:
                return
            removed = self.roster.pop(idx)
            if self.selected_roster_idx >= len(self.roster) and self.roster:
                self.selected_roster_idx = len(self.roster) - 1
            self.text_log.add_message(f"Deleted {removed.name} from roster.")

        self.text_log.prompt("Delete? (Y/N):", _on_confirm, single_char=True)

    # The choosing steps' options: (letter, word, note). The letters are the
    # ones the prompts have always taken; the first of each list is what an
    # unknown letter has always given (Human, Fighter).
    SEX_OPTIONS = (("M", "Male", ""), ("F", "Female", ""), ("O", "Other", ""))
    _RACE_ORDER = (Race.HUMAN, Race.ELF, Race.DWARF, Race.BOBBIT, Race.FUZZY)
    _PROF_ORDER = (
        ("F", Profession.FIGHTER), ("C", Profession.CLERIC), ("W", Profession.WIZARD),
        ("T", Profession.THIEF), ("P", Profession.PALADIN), ("B", Profession.BARBARIAN),
        ("R", Profession.RANGER), ("L", Profession.LARK), ("I", Profession.ILLUSIONIST),
        ("D", Profession.DRUID), ("A", Profession.ALCHEMIST),
    )
    STAT_NAMES = ("Strength", "Dexterity", "Intelligence", "Wisdom")

    @classmethod
    def creation_options(cls, step: int) -> list[tuple[str, str, str]]:
        """(letter, word, note) for choosing step 1 (sex), 2 (race), 3 (class)."""
        if step == 1:
            return list(cls.SEX_OPTIONS)
        if step == 2:
            return [
                (r.code, r.name.title(),
                 f"STR {r.max_str}  DEX {r.max_dex}  INT {r.max_int}  WIS {r.max_wis}")
                for r in cls._RACE_ORDER
            ]
        if step == 3:
            return [(code, p.name.title(), "") for code, p in cls._PROF_ORDER]
        return []

    def _note(self, msg: str) -> None:
        """A creation message: logged, and shown on the creation screen."""
        self._create_note = msg
        self.text_log.add_message(msg)

    def _end_creation(self) -> None:
        self._create_step = None
        self._creating_char = False

    def _start_create_character(self) -> None:
        """Start the five creation steps: name, sex, race, class, stats.

        Each step keeps its text prompt, so typing works as it always has
        (a name and Enter; M/F/O; the race and class letters; each stat's
        number and Enter). Up/Down choose and Enter takes the highlighted
        choice; at the stats Up/Down choose a stat, Left/Right adjust it,
        and Enter accepts once all 50 points are shared. Esc goes back a
        step, or cancels at the name.

        Java truth: ``exodus/ManagePartyScreen.java:165-199,355-367`` — the
        stat sliders allocate each of STR/DEX/INT/WIS in 5..25, the total may
        not exceed 50 (over-budget apply is refused, nothing is committed),
        the name keeps at most 12 letters (LairWare UltimaMacIF.c:2430-2432),
        and a created character
        starts with health/food/gold = 150 and a readied Dagger and Cloth
        (LairWare UltimaMain.c:814-817). Stat
        validation is delegated to ``Character.validate_creation``.
        """
        self._new_char_data = {}
        self._create_note = ""
        self._creating_char = True
        self._prompt_name()

    # -- the steps' prompts --------------------------------------------------

    def _prompt_name(self, prefill: str = "") -> None:
        self._create_step = 0
        self.text_log.prompt(f"Character Name (up to {CREATION_MAX_NAME} chars):", self._step_name)
        self.text_log.input_buffer = prefill

    def _prompt_sex(self) -> None:
        # Sex: [M]ale [F]emale [O]ther — "Other" reinstated per original
        # rules (user-directed deviation from Java's SexType, which has
        # only Male/Female; see Sex.OTHER in constants.py). Invalid input
        # re-prompts, matching the wizard's stat re-prompt behavior.
        self._enter_choice_step(1, self._new_char_data.get("sex"))
        self.text_log.prompt("Sex: [M]ale [F]emale [O]ther:", self._step_sex, single_char=True)

    def _prompt_race(self) -> None:
        self._enter_choice_step(2, self._new_char_data.get("race"))
        self.text_log.prompt("Race: [H]uman [E]lf [D]warf [B]obit [F]uzzy:", self._step_race, single_char=True)

    def _prompt_class(self) -> None:
        self._enter_choice_step(3, self._new_char_data.get("prof"))
        self.text_log.prompt(
            "Class: [F]ight [C]leric [W]iz [T]hief [P]al [R]ang [B]arb:", self._step_profession, single_char=True
        )

    def _enter_choice_step(self, step: int, chosen: Any) -> None:
        """Open a choosing step with its earlier choice (if any) highlighted."""
        self._create_step = step
        values = self._step_values(step)
        self._create_cursor = values.index(chosen) if chosen in values else 0

    @classmethod
    def _step_values(cls, step: int) -> list[Any]:
        if step == 1:
            return [Sex.MALE, Sex.FEMALE, Sex.OTHER]
        if step == 2:
            return list(cls._RACE_ORDER)
        return [p for _, p in cls._PROF_ORDER]

    def _start_stat_allocation(self) -> None:
        self._create_step = 4
        self._new_char_data["stats"] = [CREATION_MIN_STAT] * 4
        self._new_char_data["typed"] = set()
        self._new_char_data["stat_step"] = 0
        self._stat_sel = 0
        self.text_log.add_message("Allocate stats: each 5-25, total must not exceed 50.")
        self._prompt_next_stat()

    def _prompt_next_stat(self) -> None:
        step = self._new_char_data["stat_step"]
        self._stat_sel = step
        self.text_log.prompt(f"{self.STAT_NAMES[step]} (5-25):", self._step_stat, single_char=False)

    # -- the steps' answers (typed, or the highlighted choice) ---------------

    def _step_name(self, name_str: str) -> None:
        # A name is at most 12 letters: LairWare cuts the name field at
        # 12 (UltimaMacIF.c:2430-2432) and stores name bytes 0..11
        # (UltimaMacIF.c:2492-2496). Java allowed 16.
        name = name_str.strip()[:CREATION_MAX_NAME]
        if not name:
            name = f"Hero{len(self.roster) + 1}"
        self._new_char_data["name"] = name
        self._create_note = ""
        self._prompt_sex()

    def _step_sex(self, sex_str: str) -> None:
        code = sex_str.strip().upper()[:1]
        sexes = {"M": Sex.MALE, "F": Sex.FEMALE, "O": Sex.OTHER}
        if code not in sexes:
            self._note("Enter M, F, or O.")
            self._prompt_sex()
            return
        self._new_char_data["sex"] = sexes[code]
        self._create_note = ""
        self._prompt_race()

    def _step_race(self, race_str: str) -> None:
        race_map = {r.code: r for r in self._RACE_ORDER}
        code = race_str.strip().upper()[:1]
        self._new_char_data["race"] = race_map.get(code, Race.HUMAN)
        self._create_note = ""
        self._prompt_class()

    def _step_profession(self, prof_str: str) -> None:
        prof_map = dict(self._PROF_ORDER)
        code = prof_str.strip().upper()[:1]
        self._new_char_data["prof"] = prof_map.get(code, Profession.FIGHTER)
        self._create_note = ""
        # Note: the old portrait-number prompt step was removed (user
        # ruling: "dump the faces/images for characters" — the original
        # game had no character portraits). The wizard goes straight from
        # Class to stat allocation; portrait_index stays a save-only field.
        self._start_stat_allocation()

    def _step_stat(self, raw: str) -> None:
        step = self._new_char_data["stat_step"]
        name = self.STAT_NAMES[step]
        try:
            value = int(raw.strip())
        except ValueError:
            self._note(f"{name}: enter a number 5-25.")
            self._prompt_next_stat()
            return
        if not (CREATION_MIN_STAT <= value <= CREATION_MAX_STAT):
            self._note(f"{name} ({value}) must be 5-25.")
            self._prompt_next_stat()
            return
        self._new_char_data["stats"][step] = value
        typed = self._new_char_data.setdefault("typed", set())
        typed.add(step)
        if len(typed) == len(self.STAT_NAMES):
            # All four typed (in order, the way the prompts ask): done.
            self._assemble_character()
            return
        # The next stat not typed yet, after this one.
        self._new_char_data["stat_step"] = next(
            i % 4 for i in range(step + 1, step + 5) if i % 4 not in typed
        )
        self._prompt_next_stat()

    # -- the arrows, Enter and Esc -------------------------------------------

    def _handle_create_key(self, event: pygame.event.Event) -> bool:
        """The creation steps' own keys; False leaves the key to the prompt."""
        key = event.key
        step = self._create_step
        if key == pygame.K_ESCAPE:
            self._create_back()
            return True
        enter = key in (pygame.K_RETURN, pygame.K_KP_ENTER)
        if step in (1, 2, 3):
            n = len(self._step_values(step))
            if key in (pygame.K_UP, pygame.K_DOWN):
                self._create_cursor = (self._create_cursor + (1 if key == pygame.K_DOWN else -1)) % n
                return True
            if enter:
                code = self.creation_options(step)[self._create_cursor][0]
                self.text_log.submit_input(code)
                return True
            return False
        if step == 4:
            if key in (pygame.K_UP, pygame.K_DOWN):
                # The typed number goes to the stat the arrows chose.
                sel = (self._stat_sel + (1 if key == pygame.K_DOWN else -1)) % 4
                self._new_char_data["stat_step"] = sel
                self._prompt_next_stat()
                return True
            if key in (pygame.K_LEFT, pygame.K_RIGHT):
                self._adjust_stat(1 if key == pygame.K_RIGHT else -1)
                return True
            if enter and not self.text_log.input_buffer.strip():
                self._accept_stats()
                return True
        return False

    def stat_limit(self, idx: int) -> int:
        """The most stat ``idx`` may start with: 25, or the race's maximum."""
        race = self._new_char_data.get("race", Race.HUMAN)
        caps = (race.max_str, race.max_dex, race.max_int, race.max_wis)
        return min(CREATION_MAX_STAT, caps[idx])

    def points_left(self) -> int:
        return CREATION_MAX_POINTS - sum(self._new_char_data.get("stats", [CREATION_MIN_STAT] * 4))

    def _adjust_stat(self, delta: int) -> None:
        stats = self._new_char_data["stats"]
        i = self._stat_sel
        new = stats[i] + delta
        if new < CREATION_MIN_STAT or new > self.stat_limit(i) or (delta > 0 and self.points_left() <= 0):
            if self.audio is not None:
                self.audio.play_sfx("negative")
            return
        stats[i] = new
        self._create_note = ""

    def _accept_stats(self) -> None:
        """Enter with nothing typed: the shared points, once none are left."""
        left = self.points_left()
        if left != 0:
            self._note(f"{left} points left to share." if left > 0 else f"{-left} points too many.")
            return
        self.text_log.handle_escape()  # the stat prompt is answered by the arrows
        self._assemble_character()

    def _create_back(self) -> None:
        """Esc: back one step, or cancel the creation at the name."""
        step = self._create_step
        self.text_log.handle_escape()
        self._create_note = ""
        if step == 0:
            self._end_creation()
            self.text_log.add_message("Creation cancelled.")
        elif step == 1:
            self._prompt_name(self._new_char_data.get("name", ""))
        elif step == 2:
            self._prompt_sex()
        elif step == 3:
            self._prompt_race()
        else:
            self._prompt_class()

    def creation_view(self) -> dict[str, Any]:
        """What the creation screen shows: each step's value (the highlighted
        choice included, so the preview fills in as you go)."""
        d = self._new_char_data
        step = self._create_step if self._create_step is not None else 0
        hover = None
        if step in (1, 2, 3):
            hover = self._step_values(step)[self._create_cursor]
        name = self.text_log.input_buffer.strip() if step == 0 else d.get("name", "")
        return {
            "step": step,
            "name": name,
            "sex": hover if step == 1 else d.get("sex") if step > 1 else None,
            "race": hover if step == 2 else d.get("race") if step > 2 else None,
            "prof": hover if step == 3 else d.get("prof") if step > 3 else None,
            "name_done": d.get("name", "") if step > 0 else "",
            "sex_done": d.get("sex") if step > 1 else None,
            "race_done": d.get("race") if step > 2 else None,
            "prof_done": d.get("prof") if step > 3 else None,
            "options": self.creation_options(step),
            "cursor": self._create_cursor,
            "stats": list(d.get("stats", [CREATION_MIN_STAT] * 4)),
            "left": self.points_left(),
            "stat_sel": self._stat_sel,
            "note": self._create_note,
        }

    def _assemble_character(self) -> None:
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
            self._note(err)
            # Java refuses the apply and keeps the allocation UI open:
            # restart the stat prompts with nothing committed.
            self._start_stat_allocation()
            return

        self._end_creation()
        if len(self.roster) >= ROSTER_SLOTS:
            self.text_log.add_message("The roster is full (20 adventurers)!")
            return

        # Starting record: health/food/gold = 150 (ManagePartyScreen.java:
        # 185-192), plus LairWare's starting kit: one Dagger and one Cloth,
        # both readied (LairWare UltimaMain.c:814-817, Player[41]/[40]
        # Cloth readied, Player[49]/[48] Dagger readied). Max MP is
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
            weapon=WeaponType.DAGGER,
            armor=ArmorType.CLOTH,
            roster_slot=self._free_slot(),
            # portrait_index keeps its default (43): the field survives for
            # save compatibility but the creation wizard never asks for it
            # and no UI renders it (user ruling, see _step_profession).
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
        self._follow_selection()
        self.text_log.add_message(f"Created {name} ({prof.name})! Added to roster.")

    def _embark(self) -> None:
        """Form the chosen party and launch a new game on Sosaria.

        LairWare Form (UltimaNew.c:201-229) starts fresh: a cleared party
        record, on foot at the start square, no moves, and ResetSosaria()
        for the world. The party built here is a new ``Party`` with those
        defaults, and the overworld opens with no saved world. A party that
        already exists can't be formed again (user ruling Q2)."""
        if self._refuse_party_in_use():
            return
        if not self.party.members:
            self.text_log.add_message("Cannot embark! Form a party with at least 1 member.")
            return

        # Save roster and party (Java ManagePartyScreen.java:262-293 writes
        # both records; embark persists before the overworld opens)
        try:
            self._write_party_saves()
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

    # LairWare DrawOrganizeMenu's row words.
    _STATUS_WORD = {"P": "Poisoned ", "D": "Dead ", "A": "Ashes "}
    _SEX_WORD = {"M": "Male", "F": "Female", "O": "Other"}

    def _in_party(self, char: Character) -> bool:
        return any(same_record(m, char) for m in self.party.members)

    @classmethod
    def describe(cls, char: Character) -> str:
        """LairWare's row text: status (when not good), race, class, sex."""
        st = getattr(char.status, "value", str(char.status))[:1]
        race = getattr(char.race, "name", str(char.race)).title()
        prof = getattr(char.profession, "name", str(char.profession)).title()
        sex = cls._SEX_WORD.get(getattr(char.sex, "value", str(char.sex))[:1], "")
        return f"{cls._STATUS_WORD.get(st, '')}{race} {prof} {sex}".strip()

    def render(self, surface: pygame.Surface) -> None:
        """THE PARTY, or A NEW ADVENTURER while one is being created
        (py_exodus.ui.roster_view draws both)."""
        from py_exodus.ui import roster_view
        from py_exodus.ui.stats_panel import _equipment_display_names

        names = _equipment_display_names(self.asset_mgr)
        if self._create_step is not None:
            roster_view.render_creation(surface, self, names)
        else:
            self._follow_selection()
            roster_view.render_roster(surface, self, names)
