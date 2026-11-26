"""Tactical grid CombatScreen wrapping CombatArena for 11x11 battles."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pygame

from py_exodus.ui.hit_orb import HIT_ORB_COLOURS, draw_hit_orb

from py_exodus import debug
from py_exodus.combat.arena import Action, ActionType, CombatArena
from py_exodus.combat.auto_combat import choose_auto_combat_action
from py_exodus.combat.magic import (
    DIRECTIONAL_SPELLS,
    TARGETED_MEMBER_SPELLS,
    PROJECTILE_SPELLS,
    get_castable_spell_types,
    resolve_spell,
)
from py_exodus.spell_menu import letter_resolution, spell_menu_entries, spell_menu_prompt_lines
from py_exodus.constants import (
    COMBAT_HEIGHT,
    COMBAT_WIDTH,
    TILE_SIZE,
    ArmorType,
    Direction,
    Spell,
    WeaponType,
)
from py_exodus.entities.party import PartyDeathException, PartyMember
from py_exodus.screens.base import BaseScreen
from py_exodus.ui.renderer import WorldRenderer
from py_exodus.ui.stats_panel import StatsPanel
from py_exodus.ui.text_log import (
    EGA_BLACK,
    EGA_BRIGHT_CYAN,
    EGA_BRIGHT_GREEN,
    EGA_BRIGHT_RED,
    EGA_DARK_GRAY,
    EGA_WHITE,
    EGA_YELLOW,
    TextLog,
    get_hud_font,
)

if TYPE_CHECKING:
    from py_exodus.assets import AssetManager
    from py_exodus.audio import AudioManager
    from py_exodus.entities.party import Party
    from py_exodus.world.map import ConflictMap


# UltimaSpellCombat.c:938-955: ``count = 0x2F`` counted down once per key
# poll; the 47th pass of keyloop presses Space after 46 polls.
COMBAT_PASS_POLLS = 0x2F - 1


class CombatScreen(BaseScreen):
    """Interactive screen for 11x11 tactical turn-based combat encounters."""

    allows_quick_reference = True

    def __init__(
        self,
        party: Party,
        combat_map: ConflictMap,
        creature_tile: str = "orc",
        asset_mgr: AssetManager | None = None,
        audio: AudioManager | None = None,
        return_screen: BaseScreen | None = None,
        monster_count: int | None = None,
        context_map_id: int | None = None,
        encounter_x: int | None = None,
        encounter_y: int | None = None,
        encounter_tile_walkable: bool | None = None,
        creature_variant: int = 0,
        **kwargs: Any,
    ) -> None:
        super().__init__(return_screen=return_screen, **kwargs)
        self.party = party
        self.combat_map = combat_map
        self.creature_tile = creature_tile
        self.asset_mgr = asset_mgr
        self.audio = audio

        self.arena = CombatArena(
            party=party,
            combat_map=combat_map,
            creature_tile=creature_tile,
            asset_mgr=asset_mgr,
            monster_count=monster_count,
            context_map_id=context_map_id,
            encounter_x=encounter_x,
            encounter_y=encounter_y,
            encounter_tile_walkable=encounter_tile_walkable,
            creature_variant=creature_variant,
        )

        self.world_renderer = (
            WorldRenderer(asset_mgr) if asset_mgr is not None else None
        )
        self.stats_panel = StatsPanel(asset_mgr=self.asset_mgr)
        self.text_log = TextLog(max_lines=5, wrap_width=64)

        # Message parity (item 3): Java logs NOTHING when a combat opens
        # (the encounter tile spawns the CombatScreen silently) — the
        # invented "Ambushed by ..." seed line is gone; only arena-produced
        # messages are mirrored below.
        for msg in self.arena.log_messages:
            self.text_log.add_message(msg)
        self.arena.log_messages.clear()

        self._prompt_ran_action = False
        self._log_turn_marker()

        self._pending_action_type: ActionType | None = None
        self.awaiting_exit_ack = False
        self._end_combat_notified = False
        self.flash_timer: float = 0.0
        self.combat_fx: list[dict[str, Any]] = []
        self.dying_monsters: list[dict[str, Any]] = []
        self._anim_stage: str | None = None
        self._pending_fx: dict[str, Any] | None = None
        self._pending_dying: list[dict[str, Any]] = []
        self._pending_action: Action | None = None
        self._pending_res: Any = None
        self.auto_combat: bool = False
        self.auto_combat_interval: float = 0.12
        self._auto_combat_timer: float = 0.0
        # The member command wait's idle count (UltimaSpellCombat.c:938-970),
        # in game time: polls waited, and whose wait it is.
        from py_exodus.world.realtime import PollClock

        self._idle_clock = PollClock()
        self._idle_polls = 0
        self._idle_member: int | None = None
        # Combat Z shown; the member passes when Ztats is closed.
        self._ztats_pass_pending = False

    def on_enter(self) -> None:
        """Sync auto-combat flag from manager when entering combat."""
        super().on_enter()
        if self.manager is not None and (
            getattr(self.manager, "autoplay_enabled", False)
            or getattr(self.manager, "auto_combat_enabled", False)
        ):
            self.auto_combat = True

    @property
    def active_party_member(self) -> PartyMember | None:
        """Return currently active party member taking turn in combat."""
        return self.party.get_member(self.arena.active_party_member_idx)

    def _log_turn_marker(self) -> None:
        """PLAYABILITY AFFORDANCE (task 6, 2026-11-14) — NOT message parity.

        GBC shows whose turn it is with the blink cursor + member stat
        window (GBC battle2.c:297, battle.c:262) and logs no text; Java
        logs none either. This port's combat channel is the text log, so
        the marker line names the active member once per event: at combat
        start, after a consuming action advances (or rolls) the turn, and
        whenever a non-consuming action or disarmed prompt returns the
        turn to the same member. Never called per-frame."""
        if self.arena.is_finished:
            return
        member = self.active_party_member
        if member is not None:
            self.text_log.add_message(f"{member.name}'s turn.")

    def on_enter(self) -> None:
        super().on_enter()
        # Back from the Book or a quick-reference card: the member's command
        # wait starts its count afresh (UltimaSpellCombat.c:938), as after
        # any key; the key that opened the card never reached this screen.
        self._reset_idle()
        if self.audio is not None:
            self.audio.play_music("combat")

    def on_exit(self) -> None:
        super().on_exit()
        if self.audio is not None:
            self.audio.stop_music()

    def handle_event(self, event: pygame.event.Event) -> None:
        # Mouse wheel scrolls the shared text log back through history
        # (Java LogScrollPane affordance; wheel is never a combat command).
        if event.type == pygame.MOUSEWHEEL:
            self.text_log.handle_wheel(event)
            return

        if event.type != pygame.KEYDOWN:
            return
        # Any key ends the member's command wait (GetKeyMouse, then the
        # next wait starts at count = 0x2F again; UltimaSpellCombat.c:938).
        self._reset_idle()

        # LairWare DoStats (UltimaMacIF.c:1385-1395): Ztats is modal; the
        # key that ends it, any key, is swallowed.
        if self.stats_panel.inspect_index is not None:
            self.stats_panel.inspect_index = None
            if self._ztats_pass_pending:
                # Combat Z reaches ``goto plrdone`` only now
                # (UltimaSpellCombat.c:1066-1069).
                self._ztats_pass_pending = False
                try:
                    self._execute_action(Action.pass_turn())
                except PartyDeathException:
                    self.check_party_death()
            return

        if self._anim_stage is not None:
            self.flush_animations()

        # If waiting for prompt input (e.g. Direction or Spell code)
        if self.text_log.is_waiting_for_input:
            self._prompt_ran_action = False
            self.text_log.handle_event(event)
            if (
                not self.text_log.is_waiting_for_input
                and not self._prompt_ran_action
            ):
                # The prompt was disarmed without executing an action ("Not
                # a spell!", invalid direction/member cancel, ESC, a
                # silent out-of-range menu letter): the turn returns to the
                # same member — mark it (playability affordance, task 6).
                self._log_turn_marker()
            return

        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): debug cheat harness
        # (GBC cheat.c:768-825 docheat) — F10 opens the cheat menu in
        # --debug mode only; non-debug F10 stays inert.
        if debug.DEBUG_MODE and event.key == pygame.K_F10:
            debug.open_cheat_menu(self.text_log, self.party)
            return

        # If combat is finished, any key acknowledges and exits
        if self.arena.is_finished:
            self._notify_end_combat()
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE, pygame.K_ESCAPE):
                if self.arena.is_defeat:
                    self._handle_defeat_exit()
                else:
                    self.exit_screen()
            return

        # PageUp/PageDown always scroll the text log back (arrow keys scroll
        # only inside the log's own prompt handling, when they cannot act as
        # direction/command answers).
        if self.text_log.handle_scroll_key(event.key):
            return

        if event.key in (pygame.K_TAB, pygame.K_F2):
            self.auto_combat = not self.auto_combat
            self._auto_combat_timer = 0.05
            if self.manager is not None:
                self.manager.auto_combat_enabled = self.auto_combat
            self.text_log.add_message(
                "Auto-combat ON." if self.auto_combat else "Auto-combat OFF."
            )
            return

        if self.auto_combat and event.key == pygame.K_ESCAPE:
            self.auto_combat = False
            if self.manager is not None:
                self.manager.auto_combat_enabled = False
            self.text_log.add_message("Auto-combat OFF.")
            return

        if event.key == pygame.K_z:
            # LairWare combat Z (UltimaSpellCombat.c:1066-1069): ``Stats(1,
            # chnum + 1)`` shows the active member (no question), then
            # ``goto plrdone``: that member's turn is over once the modal
            # stats are closed (the pass runs in the close branch above).
            idx = self.arena.active_party_member_idx
            if self.party.get_member(idx) is None:
                return
            from py_exodus.screens.member_prompts import show_ztats

            show_ztats(self.text_log, self.stats_panel, self.party, idx)
            self._ztats_pass_pending = True
            return

        # Standard combat keys
        active_member = self.active_party_member
        if active_member is None:
            return

        # Java CombatScreen.keyUp (CombatScreen.java:290-362) wraps the whole
        # key pipeline in its PartyDeathException catch → the return screen
        # routes partyDeath. In a tile-effect wipe mid-move that matters.
        try:
            self._on_combat_key(event)
        except PartyDeathException:
            self.check_party_death()

    def _on_combat_key(self, event: pygame.event.Event) -> None:
        # Movement keys (Arrow keys and Keypad)
        if event.key in (pygame.K_UP, pygame.K_KP8):
            self._execute_action(Action.move(Direction.NORTH))
        elif event.key in (pygame.K_DOWN, pygame.K_KP2):
            self._execute_action(Action.move(Direction.SOUTH))
        elif event.key in (pygame.K_LEFT, pygame.K_KP4):
            self._execute_action(Action.move(Direction.WEST))
        elif event.key in (pygame.K_RIGHT, pygame.K_KP6):
            self._execute_action(Action.move(Direction.EAST))
        elif event.key in (pygame.K_SPACE, pygame.K_p):
            self._execute_action(Action.pass_turn())
        elif event.key == pygame.K_a:  # Attack command
            self._prompt_attack()
        elif event.key == pygame.K_c:  # Cast command
            self._prompt_cast()
        elif event.key == pygame.K_n:  # Negate time: burn a powder for QUICKNESS 10
            self._negate_time()
        elif event.key == pygame.K_r:  # Ready weapon
            self._prompt_ready_weapon()
        elif event.key == pygame.K_w:  # Wear armor
            self._prompt_wear_armor()

    def _negate_time(self) -> None:
        """Java CombatScreen.negateTime (CombatScreen.java:331-332, 503-514):
        the first member holding powder burns one for a QUICKNESS aura; with
        none held the log reads "None!". N consumes no combat turn. The
        duration is 10 per USER-DIRECTED GBC-RULES DEVIATION (2026-11-14)
        (GBC battle2.c:722-733; LW UltimaMain.c:2129-2139) — superseding the
        old Java 6-turn reading."""
        from py_exodus.aura import AuraType

        for pm in self.party.members:
            if getattr(pm, "powder", 0) > 0:
                pm.powder -= 1
                self.text_log.add_message("Stop time with a powder!")
                self.party.aura.set(AuraType.QUICKNESS, 10)
                break
        else:
            self.text_log.add_message("None!")
        # N consumes no combat turn: the turn returns to the same member
        # (affordance marker, see _log_turn_marker).
        self._log_turn_marker()

    def _prompt_attack(self) -> None:
        """Prompt active member for attack direction."""
        active = self.active_party_member
        if not active:
            return

        def _on_dir(d_str: str) -> None:
            d = Direction.from_name_or_key(d_str)
            if d is None:
                self.text_log.add_message("Invalid direction!")
                return
            self._execute_action(Action.attack(d))

        self.text_log.prompt("Direction? (N,S,E,W):", callback=_on_dir, single_char=True)

    def _prompt_cast(self) -> None:
        """Prompt active member for spell casting.

        Java truth (CombatScreen.java:322-330 + SpellInputProcessor.java
        :31-46): C uses the ACTIVE member (no member prompt), builds the
        combat spell menu with MapType.combat and SpellInputProcessor prints
        the rows (``{letter} - {SPELL} ({cost})``) and reads letters from
        that SAME list. "No spells to cast!" remains the canonical line when
        the profession gate upstream (``get_castable_spell_types``) opens no
        menu at all.

        USER-DIRECTED RULING (2026-11-15): fixed spell letters
        (B=APPAR_UNEM always); availability refused at attempt — supersedes
        the Java getCastables letter compaction (Constants.java:751-762)
        adopted 2026-11-14. Each menu is the discipline's FULL FIXED A-P
        list (name + fixed letter + MP cost); letters never move with mana
        or context. py splits the menus per RESOLVED discipline (the
        druid/ranger dual gate upstream), so each menu is one
        ``spell_menu_entries`` call with the chosen discipline and a letter
        is classified AT ATTEMPT through ``letter_resolution``: "Not Here!"
        when the context mask refuses the spell (no cast, no mana, menu
        disarms, caster stays active), "Not a spell!" for out-of-list keys,
        and the canonical MP refusal AT LETTER SELECTION from the prompt
        layer itself for unaffordable (but listed) letters — BEFORE any
        "Direction?"/"On who?" prompt (F2 AMENDMENT 2026-11-15);
        ``cast_spell``'s prevalidation stays for direct-API callers and the
        FULL MP cheat skips the gate.
        """
        active = self.active_party_member
        if not active:
            return

        char = active.character
        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): debug cheat
        # harness (GBC cheat.c:414-825) — FULL MP tops the caster up at the
        # combat cast prompt open (same hook as the other three screens).
        debug.apply_full_mp(active)
        types = get_castable_spell_types(char.profession)
        if not types:
            # Java's canonical no-castables line (CombatScreen.java:326 —
            # the pressed-C branch with an empty getCastables map).
            self.text_log.add_message("No spells to cast!")
            # Refused cast: the turn returns to the same member (affordance).
            self._log_turn_marker()
            return

        def _ask_spell_code(discipline: str) -> None:
            type_label = "Wizard" if discipline == "wizard" else "Cleric"
            # USER-DIRECTED RULING (2026-11-15): fixed spell letters
            # (B=APPAR_UNEM always) — the full fixed A-P list is captured
            # once and drives BOTH the printed rows and the attempt-time
            # letter classification (context "combat").
            entries = spell_menu_entries(discipline)
            # Rows render through the same message stream the ready-weapon
            # menu uses (screen menus print in the log, then arm a prompt).
            for line in spell_menu_prompt_lines(entries):
                self.text_log.add_message(line)

            def _on_spell(code: str) -> None:
                found_spell, refusal = letter_resolution(entries, code, "combat")
                if refusal is not None:
                    # Two prompt-layer refusals, both pre-execution (no
                    # SpellResult produced, no cast, no mana — USER-DIRECTED
                    # RULING 2026-11-15): "Not a spell!" for a key outside
                    # the fixed A-P codes (Java SpellInputProcessor.java
                    # :69-72: any key failing the code guard — digits, ESC,
                    # a non-listed letter) and "Not Here!" for a fixed code
                    # whose spell fails canCastLocation(MapType.combat)
                    # (Constants.java:779-781). Either way the menu
                    # DISARMS: input returns to the screen multiplexer with
                    # no row re-print, the player re-presses C to see the
                    # list again, and the turn stays with the active member.
                    self.text_log.add_message(refusal)
                    return

                # F2 AMENDMENT (USER-DIRECTED, 2026-11-15): the MP refusal
                # fires AT LETTER SELECTION — immediately after the letter
                # resolves, BEFORE the "Direction?" / "On who?" prompts —
                # with the canonical SpellUtil.java:58 string. Previously
                # the target/direction prompt ran first and the refused
                # cast_spell call surfaced its prevalidation string only
                # after that selection; the ruling moves the refusal up one
                # step. The menu DISARMS on the refusal (same shape as the
                # other attempt-refusals: no re-print, the player re-presses
                # C) and the turn stays with the active member — no
                # _execute_action, no round advance. cast_spell's mana
                # prevalidation stays for direct-API callers; the FULL MP
                # cheat (CHEATS.full_mp — "MP NEVER DECREASES",
                # cheat.c:414-825) skips this gate, as its prompt-open
                # top-up already does.
                if not debug.CHEATS.full_mp and char.mp < found_spell.cost:
                    self.text_log.add_message("Thou dost not have enough magic points!")
                    return

                def _gather(prompt_spell: Spell, cleric: Spell | None = None) -> None:
                    """The target or direction the (cleric) spell needs."""
                    if prompt_spell in DIRECTIONAL_SPELLS:
                        def _on_dir(d_str: str) -> None:
                            d = Direction.from_name_or_key(d_str)
                            if d is None:
                                self.text_log.add_message("Invalid direction!")
                                return
                            self._execute_action(
                                Action.cast(found_spell, direction=d, cleric_spell=cleric))

                        self.text_log.prompt("Direction? (N,S,E,W):", callback=_on_dir, single_char=True)
                    elif prompt_spell in TARGETED_MEMBER_SPELLS:
                        def _on_target(target_str: str) -> None:
                            try:
                                t_idx = int(target_str.strip()) - 1
                                target_m = self.party.get_member(t_idx)
                            except ValueError:
                                target_m = None
                            if target_m is None:
                                self.text_log.add_message("Invalid member #!")
                                return
                            self._execute_action(
                                Action.cast(found_spell, target_member=target_m, cleric_spell=cleric))

                        self.text_log.prompt("On who? (1-4):", callback=_on_target, single_char=True)
                    else:
                        self._execute_action(Action.cast(found_spell, cleric_spell=cleric))

                if found_spell == Spell.FAL_DIVI:
                    # LairWare case 9 (UltimaSpellCombat.c:231-235): the same
                    # caster picks a cleric letter; ProcessMagic charges its
                    # MP and casts it, and the turn is spent (ledger P-20).
                    c_entries = spell_menu_entries("cleric")
                    for line in spell_menu_prompt_lines(c_entries):
                        self.text_log.add_message(line)

                    def _on_cleric(c_code: str) -> None:
                        c_spell, c_refusal = letter_resolution(c_entries, c_code, "combat")
                        if c_refusal is not None:
                            self.text_log.add_message(c_refusal)
                            return
                        _gather(c_spell, c_spell)

                    self.text_log.prompt("Cleric Spell? (A-P):", callback=_on_cleric, single_char=True)
                else:
                    _gather(found_spell)

            self.text_log.prompt(f"{type_label} Spell? (A-P):", callback=_on_spell, single_char=True)

        if len(types) > 1:
            def _on_type(t_str: str) -> None:
                t = t_str.strip().upper()
                if t in ("W", "WIZARD"):
                    _ask_spell_code("wizard")
                elif t in ("C", "CLERIC"):
                    _ask_spell_code("cleric")
                else:
                    self.text_log.add_message("Invalid choice! Enter W or C.")

            self.text_log.prompt("Spell Type? [W]izard or [C]leric:", callback=_on_type, single_char=True)
        else:
            _ask_spell_code(types[0])

    def _prompt_ready_weapon(self) -> None:
        """Prompt active member to ready a weapon (A-P)."""
        active = self.active_party_member
        if not active:
            return

        weapon_types = list(WeaponType)
        self.text_log.add_message(f"-- Ready Weapon for {active.name} --")
        for w_idx, wt in enumerate(weapon_types):
            letter = chr(ord('A') + w_idx)
            if wt == WeaponType.NONE:
                self.text_log.add_message(f"{letter} - Hands")
                continue
            cnt = active.weapons.get(wt, 0)
            is_equipped = (active.weapon == wt)
            if cnt > 0 or is_equipped:
                status_tag = " (readied)" if is_equipped else f" ({cnt})"
                self.text_log.add_message(f"{letter} - {wt.name.capitalize()}{status_tag}")

        def _on_weap(w_code: str) -> None:
            c = w_code.strip().upper()
            if not c:
                return
            w_idx = ord(c[0]) - ord('A')
            if 0 <= w_idx < len(weapon_types):
                success = active.ready_weapon(w_idx, self.asset_mgr)
                # Java's ReadyWearInputAdapter result lines
                # (CombatScreen.java:995-997): exactly "Success!" /
                # "Failed!" — no member or item named. An out-of-range
                # letter is a non-A..P key: Java's keyUp handles A..P only
                # (CombatScreen.java:967) and falls through silently.
                if success:
                    self.text_log.add_message("Success!")
                    self._execute_action(Action.pass_turn())
                else:
                    self.text_log.add_message("Failed!")
            # Beyond the enum list is a non-A..P key: Java's keyUp only
            # handles A..P (CombatScreen.java:967) and falls through
            # silently, so no message here.

        self.text_log.prompt("Ready Weapon? (A-P): ", callback=_on_weap, single_char=True)

    def _prompt_wear_armor(self) -> None:
        """Prompt active member to wear armor (A-H)."""
        active = self.active_party_member
        if not active:
            return

        armor_types = list(ArmorType)
        self.text_log.add_message(f"-- Wear Armor for {active.name} --")
        for a_idx, at in enumerate(armor_types):
            letter = chr(ord('A') + a_idx)
            if at == ArmorType.NONE:
                self.text_log.add_message(f"{letter} - Skin")
                continue
            cnt = active.armors.get(at, 0)
            is_equipped = (active.armor == at)
            if cnt > 0 or is_equipped:
                status_tag = " (worn)" if is_equipped else f" ({cnt})"
                self.text_log.add_message(f"{letter} - {at.name.capitalize()}{status_tag}")

        def _on_arm(a_code: str) -> None:
            c = a_code.strip().upper()
            if not c:
                return
            a_idx = ord(c[0]) - ord('A')
            if 0 <= a_idx < len(armor_types):
                success = active.wear_armor(a_idx, self.asset_mgr)
                # Java CombatScreen.java:995-997: "Success!" / "Failed!" are
                # the only result lines; nothing names the member or item.
                if success:
                    self.text_log.add_message("Success!")
                    self._execute_action(Action.pass_turn())
                else:
                    self.text_log.add_message("Failed!")
            # Beyond the enum list is a non-A..H-equivalent key: Java's keyUp
            # only handles A..P (CombatScreen.java:967) and falls through
            # silently, so no message here.

        self.text_log.prompt("Wear Armor? (A-H): ", callback=_on_arm, single_char=True)

    def _execute_action(self, action: Action) -> None:
        """Execute player action in CombatArena and sequence visual FX / monster turns."""
        if self._anim_stage is not None:
            self.flush_animations()

        active_before = self.active_party_member
        p_idx = self.arena.active_party_member_idx
        start_pos = self.arena.player_positions.get(p_idx, (5, 5))

        # Snapshot living monsters to keep dying monsters visible during hit
        # animations. Hidden camouflaged monsters are excluded: Java never
        # draws an invisible creature (CombatScreen.java:236-238), so a death
        # that was never seen cannot flash. Item 4.
        monsters_before = [
            {"tile": m.tile, "name": m.name, "x": m.x, "y": m.y, "obj": m}
            for m in self.arena.monsters if not m.is_dead and m.visible
        ]

        res = self.arena.execute_player_action(p_idx, action)
        self._prompt_ran_action = True

        current_living_objs = {m for m in self.arena.monsters if not m.is_dead}
        pending_dying = [
            {
                "tile": mb["tile"],
                "name": mb["name"],
                "x": mb["x"],
                "y": mb["y"],
                "timer": 0.35,
            }
            for mb in monsters_before
            if mb["obj"] not in current_living_objs
        ]

        self._pending_dying = pending_dying
        self._pending_action = action
        self._pending_res = res
        self._pending_fx = None

        if action.type == ActionType.CAST:
            spell_obj = action.spell
            s_name = getattr(spell_obj, "name", str(spell_obj)).upper()
            if "FULGAR" in s_name:
                color = (255, 60, 60)
            elif "DECORP" in s_name:
                color = (200, 60, 255)
            else:
                color = (0, 180, 255)

            target_pos = None
            path = []
            hit = False
            if res.spell_res is not None:
                path = res.spell_res.projectile_path
                target_pos = res.spell_res.target_pos
                hit = res.spell_res.hit

            # Java animates a projectile tracer ONLY for the directional bolt
            # branch (SpellUtil.spellMagicAttack) — the five real projectile
            # spells. A missed bolt still animates (the synthetic path is what
            # carries it), but every other cast — refusals and effect-only
            # spells — draws no tracer.
            resolved_spell = resolve_spell(getattr(action, "spell", None))
            if not path and resolved_spell in PROJECTILE_SPELLS and action.direction:
                d = action.direction
                for step in range(1, 6):
                    step_x = start_pos[0] + d.dx * step
                    step_y = start_pos[1] + d.dy * step
                    if 0 <= step_x < COMBAT_WIDTH and 0 <= step_y < COMBAT_HEIGHT:
                        path.append((step_x, step_y))
                        target_pos = (step_x, step_y)

            if not target_pos and path:
                target_pos = path[-1]

            if path or target_pos:
                self._pending_fx = {
                    "type": "spell",
                    "color": color,
                    "start_pos": start_pos,
                    "path": path,
                    "target_pos": target_pos,
                    "hit_tile": "magic" if hit else None,
                    "duration": 0.35,
                    "timer": 0.35,
                }

            # Phase 1: cast flash + magic SFX; bolt & logs wait until flash ends.
            self.flash_timer = 0.15
            self._anim_stage = "cast_flash"
            if self.audio is not None:
                self.audio.play_sfx("magic")
            return

        if action.type == ActionType.ATTACK:
            if self.audio is not None:
                # Java SecondaryInputProcessor.java:345-347: the refusal of a
                # non-exotic attack on the EXODUS map plays
                # Sound.NEGATIVE_EFFECT, never PC_ATTACK; a real attack (the
                # non-refused path, SecondaryInputProcessor.java:349) is what
                # plays PC_ATTACK.
                if res.attack_refused:
                    self.audio.play_sfx("negative_effect")
                else:
                    self.audio.play_sfx("pc_attack")

            if res.attack_res:
                ares = res.attack_res
                w_def = None
                if self.asset_mgr and active_before and hasattr(active_before, "weapon"):
                    w_name = active_before.weapon.value if hasattr(active_before.weapon, "value") else str(active_before.weapon)
                    w_def = self.asset_mgr.get_weapon(w_name)

                is_magic = w_def is not None and (w_def.magic or getattr(w_def, "hit_tile", "") == "magic")
                hit_tile = "magic" if is_magic else "fire"
                color = HIT_ORB_COLOURS[hit_tile]

                target_pos = ares.target_pos
                if not target_pos and ares.projectile_path:
                    target_pos = ares.projectile_path[-1]

                path = ares.projectile_path if ares.projectile_path else ([target_pos] if target_pos else [])
                self.combat_fx.append({
                    "type": "weapon",
                    "color": color,
                    "start_pos": start_pos,
                    "path": path,
                    "target_pos": target_pos,
                    "hit_tile": hit_tile if ares.hit else None,
                    "duration": 0.35,
                    "timer": 0.35,
                })
                self._anim_stage = "projectile"
                return

        if self.audio is not None and action.type == ActionType.MOVE:
            self.audio.play_sfx("walk_normal")

        self._complete_pending_action()

    def _complete_pending_action(self) -> None:
        """Finish an action after its visual phase: flush logs, run monster turns, check end state."""
        self._anim_stage = None
        if self._pending_dying:
            self.dying_monsters.extend(self._pending_dying)
            self._pending_dying = []

        for msg in self.arena.log_messages:
            self.text_log.add_message(msg)
        self.arena.log_messages.clear()

        if self.arena.is_party_round_done and not self.arena.is_finished:
            self.arena.execute_monster_turns()
            for msg in self.arena.log_messages:
                self.text_log.add_message(msg)
            self.arena.log_messages.clear()

        self._pending_fx = None
        self._pending_action = None
        self._pending_res = None

        # Check end states. Java logs exactly one line via
        # GameScreen.endCombat (GameScreen.java:421-437): "Victory!" on a win,
        # "Battle is lost!" when someone fled — there is no is_fled outcome
        # left (FLEE is commented out of Java's CombatScreen), so the branch
        # is gone here too. The chest/frigate placement already happened in
        # CombatArena._handle_victory (GameScreen.java:425-431).
        if self.arena.is_finished:
            if self.arena.is_victory:
                self.text_log.add_message("Victory!")
                self.text_log.add_message("Press Enter to continue.")
                if self.audio is not None:
                    # Music-class fanfare goes through play_music so the
                    # single music stream stops the combat theme before
                    # starting. User ruling (2026-11-10): a C64-style victory
                    # sting plays ONCE — pygame loops counts REPEATS, so
                    # loops=0 is the loop-once idiom. (British's castle keeps
                    # its looping fanfare via the town map theme path,
                    # town.py _play_town_music; Java's looping Sound.FANFARE,
                    # Sound.java:48, exists for that map theme, not this
                    # sting.)
                    self.audio.play_music("fanfare", loops=0)
            elif self.arena.is_defeat:
                # Message parity (item 3): Java writes NO string on a wipe —
                # endCombat branches straight to partyDeath()
                # (GameScreen.java:433-446), which logs nothing. The "Press
                # Enter to continue." line stays as py's dismissal UI only.
                self.text_log.add_message("Press Enter to continue.")

        # Turn marker (playability affordance, task 6 — see
        # _log_turn_marker): after an executed action exactly one of a
        # member advance, a round rollover, or a non-consuming
        # return-to-actor has happened; each is one turn-begin event,
        # marked once. A finished battle has no active turn to mark.
        if not self.arena.is_finished:
            self._log_turn_marker()

    def flush_animations(self) -> None:
        """Synchronously complete any pending animation stage and clear active FX."""
        self.flash_timer = 0.0
        self.combat_fx.clear()
        self.dying_monsters.clear()
        if self._anim_stage == "cast_flash":
            self._pending_fx = None
            self._complete_pending_action()
        elif self._anim_stage == "projectile":
            self._complete_pending_action()

    def _notify_end_combat(self) -> None:
        """Java CombatScreen.end (CombatScreen.java:579-587): at battle end
        the returning screen receives ``endCombat(isWon, combatMap, wounded)``
        — its post-battle bookkeeping runs exactly once. Only screens that
        implement the hook (DungeonScreen) react, matching Java's override
        split between GameScreen and DungeonScreen.endCombat.
        """
        if self._end_combat_notified:
            return
        self._end_combat_notified = True
        hook = getattr(self.return_screen, "end_combat", None)
        if callable(hook):
            hook(self.arena.is_victory)

    def _handle_defeat_exit(self) -> None:
        """Handle wipeout defeat: combat ends as a loss → game over.

        Java truth: ``exodus/GameScreen.java:433-446`` — ``endCombat`` finds
        ``!isAnyoneAlive()`` and calls ``partyDeath()`` → start screen, and
        ``exodus/CombatScreen.java:562-589`` ends combat without any revival.
        No Castle British respawn and no ``revive_all``; no extra log message
        is written here (Java's partyDeath writes none).
        """
        self.check_party_death()

    def update(self, dt: float) -> None:
        # LairWare Combat sets ``gUpdateWhere = 3; /* a la outside */`` and
        # Party[3] = 0x80 (UltimaSpellCombat.c:883-886), so DoWind keeps
        # its real-time clock through every fight, a dungeon's included.
        from py_exodus.world import realtime

        # Ztats (DoStats, gUpdateWhere 9, UltimaMacIF.c:1384-1386) stops
        # FullUpdate, and so DoWind, while it is up.
        if self.stats_panel.inspect_index is None:
            realtime.advance_wind(self.party, dt)
        fx_dt = dt
        if self.auto_combat and self.auto_combat_interval < 0.12:
            fx_dt = dt * (0.12 / max(0.01, self.auto_combat_interval))
        self.flash_timer = max(0.0, self.flash_timer - fx_dt)
        for fx in list(self.combat_fx):
            fx["timer"] -= fx_dt
            if fx["timer"] <= 0:
                self.combat_fx.remove(fx)
        for dm in list(self.dying_monsters):
            dm["timer"] -= fx_dt
            if dm["timer"] <= 0:
                self.dying_monsters.remove(dm)

        if self._anim_stage == "cast_flash" and self.flash_timer <= 0:
            if self._pending_fx is not None:
                self.combat_fx.append(self._pending_fx)
                self._pending_fx = None
                self._anim_stage = "projectile"
            else:
                self._complete_pending_action()
        elif self._anim_stage == "projectile" and not self.combat_fx:
            self._complete_pending_action()

        self._combat_idle(dt)

        if (
            self.auto_combat
            and self._anim_stage is None
            and not self.arena.is_finished
            and not self.text_log.is_waiting_for_input
            and self.stats_panel.inspect_index is None
        ):
            self._auto_combat_timer -= dt
            if self._auto_combat_timer <= 0:
                self._auto_combat_timer = self.auto_combat_interval
                action = choose_auto_combat_action(
                    self.arena, self.arena.active_party_member_idx, self.asset_mgr
                )
                try:
                    self._execute_action(action)
                except PartyDeathException:
                    self.check_party_death()

    def _reset_idle(self) -> None:
        self._idle_clock = type(self._idle_clock)()
        self._idle_polls = 0

    def _combat_idle(self, dt: float) -> None:
        """LairWare's member command wait (UltimaSpellCombat.c:938-970)::

            count = 0x2F;
            keyloop: ... count--;
            if (count == 0) { gKeyPress = ' '; }
            else { if (GetKeyMouse(0) == FALSE) goto keyloop; }

        46 polls of 5/60 s (about 3.8 s of game time) with no key and the
        active member passes (user ruling 2026-11-25, ledger B-22). Never
        inside a prompt (direction, spell, target, ready/wear), under Ztats,
        during an animation, with auto-combat or under autoplay."""
        from py_exodus.world import realtime

        idx = self.arena.active_party_member_idx
        waiting = (
            self._anim_stage is None
            and not self.arena.is_finished
            and not self.text_log.is_waiting_for_input
            and self.stats_panel.inspect_index is None
            and not self.auto_combat
            and not realtime.autoplay_on(self)
            and self.active_party_member is not None
        )
        if not waiting or idx != self._idle_member:
            self._idle_member = idx if waiting else None
            self._reset_idle()
            if not waiting:
                return
        self._idle_polls += self._idle_clock.polls(dt)
        if self._idle_polls >= COMBAT_PASS_POLLS:
            self._reset_idle()
            self.handle_event(realtime.space_event())

    def render(self, surface: pygame.Surface) -> None:
        surface.fill(EGA_BLACK)
        w, h = surface.get_width(), surface.get_height()
        scale = 3 if w >= 640 else 1
        v_size = 176 * scale

        # Render 11x11 viewport into standard 176x176 buffer
        temp_v = pygame.Surface((176, 176))
        if self.world_renderer is not None:
            self.world_renderer.render_viewport(
                temp_v,
                self.arena.combat_map,
                center_x=5,
                center_y=5,
                dest_pos=(0, 0),
            )
        else:
            self._render_grid_fallback(temp_v)

        self._render_monsters(temp_v)
        self._render_players(temp_v)
        self._apply_flash_invert(temp_v)
        self._render_combat_fx(temp_v)

        self.party.active_member_index = self.arena.active_party_member_idx

        if scale > 1:
            scaled_v = pygame.transform.scale(temp_v, (v_size, v_size))
            surface.blit(scaled_v, (0, 0))

            # Right Sidebar (Party Stats) at native high resolution
            self._render_stats_panel(
                surface,
                pygame.Rect(v_size, 0, w - v_size, h),
            )

            # Bottom HUD Text Log at native resolution
            self.text_log.render(
                surface,
                rect=pygame.Rect(0, v_size, v_size, h - v_size),
                draw_border=True,
            )
        else:
            surface.blit(temp_v, (0, 0))

            self._render_stats_panel(
                surface,
                pygame.Rect(176, 0, w - 176, h),
            )

            log_h = max(24, h - 176)
            self.text_log.render(
                surface,
                rect=pygame.Rect(0, 176, 176, log_h),
                draw_border=True,
            )

    def _render_combat_fx(self, surface: pygame.Surface) -> None:
        """Render active weapon/spell projectile travelling orbs and hit/fire bursts."""
        for fx in self.combat_fx:
            color = fx.get("color", (255, 85, 85))
            duration = fx.get("duration", 0.35)
            timer = fx.get("timer", 0.35)
            start_pos = fx.get("start_pos")
            target_pos = fx.get("target_pos")
            hit_tile = fx.get("hit_tile")

            progress = 1.0 - (timer / duration) if duration > 0 else 1.0

            # Draw projectile travelling from start_pos to target_pos
            if start_pos and target_pos:
                t_travel = min(1.0, progress / 0.7)
                curr_x = start_pos[0] + (target_pos[0] - start_pos[0]) * t_travel
                curr_y = start_pos[1] + (target_pos[1] - start_pos[1]) * t_travel
                px = int(curr_x * TILE_SIZE + TILE_SIZE // 2)
                py = int(curr_y * TILE_SIZE + TILE_SIZE // 2)

                draw_hit_orb(surface, (px, py), color)
            else:
                path = fx.get("path", [])
                for pt in path:
                    px = pt[0] * TILE_SIZE + TILE_SIZE // 2
                    py = pt[1] * TILE_SIZE + TILE_SIZE // 2
                    draw_hit_orb(surface, (px, py), color)

            # Hit burst on target once projectile arrives
            if progress >= 0.5 and target_pos and hit_tile and self.asset_mgr is not None:
                try:
                    hit_surf = self.asset_mgr.get_tile_surface(hit_tile)
                    if hit_surf is not None:
                        surface.blit(hit_surf, (target_pos[0] * TILE_SIZE, target_pos[1] * TILE_SIZE))
                except Exception:
                    pass

    def _apply_flash_invert(self, surface: pygame.Surface) -> None:
        """Invert viewport colors for classic spellcasting screen flash."""
        if self.flash_timer > 0:
            inv = pygame.Surface(surface.get_size())
            inv.fill((255, 255, 255))
            inv.blit(surface, (0, 0), special_flags=pygame.BLEND_SUB)
            surface.blit(inv, (0, 0))

    def _render_monsters(self, surface: pygame.Surface) -> None:
        font = get_hud_font(size=12)
        for m in self.arena.monsters:
            # Java CombatScreen.java:236-238 — the batch loop skips creatures
            # whose getVisible() is false, so a still-hidden camouflaged
            # monster draws nothing. Item 4.
            if m.is_dead or not m.visible:
                continue
            px = m.x * TILE_SIZE
            py = m.y * TILE_SIZE
            # Attempt tile blit if asset_mgr available
            blitted = False
            if self.asset_mgr is not None:
                try:
                    # A LairWare sheet (--tiles) has art for the named variants.
                    art = m.name.lower() if getattr(m, "variant", 0) else ""
                    t_img = self.asset_mgr.get_tile_surface(
                        art if art in self.asset_mgr.tiles else m.tile
                    )
                    if t_img is not None:
                        surface.blit(t_img, (px, py))
                        blitted = True
                except Exception:
                    pass

            if not blitted:
                rect = pygame.Rect(px + 1, py + 1, TILE_SIZE - 2, TILE_SIZE - 2)
                pygame.draw.rect(surface, EGA_BRIGHT_RED, rect)
                txt = font.render(m.name[:1], True, EGA_WHITE)
                surface.blit(txt, (px + 3, py + 1))

        # Render dying monsters during their hit burst / attack animation
        for dm in self.dying_monsters:
            px = dm["x"] * TILE_SIZE
            py = dm["y"] * TILE_SIZE
            blitted = False
            if self.asset_mgr is not None:
                try:
                    t_img = self.asset_mgr.get_tile_surface(dm["tile"])
                    if t_img is not None:
                        surface.blit(t_img, (px, py))
                        blitted = True
                except Exception:
                    pass

            if not blitted:
                rect = pygame.Rect(px + 1, py + 1, TILE_SIZE - 2, TILE_SIZE - 2)
                pygame.draw.rect(surface, EGA_BRIGHT_RED, rect)
                txt = font.render(dm["name"][:1], True, EGA_WHITE)
                surface.blit(txt, (px + 3, py + 1))

    def _render_players(self, surface: pygame.Surface) -> None:
        font = get_hud_font(size=12)
        for p_idx, (px, py) in self.arena.player_positions.items():
            member = self.party.get_member(p_idx)
            if member is None or member.is_dead():
                continue
            screen_x = px * TILE_SIZE
            screen_y = py * TILE_SIZE
            is_active = (p_idx == self.arena.active_party_member_idx)

            blitted = False
            if self.asset_mgr is not None and member is not None:
                try:
                    t_name = getattr(member.profession, "tile", "fighter")
                    t_img = self.asset_mgr.get_tile_surface(t_name)
                    if t_img is not None:
                        surface.blit(t_img, (screen_x, screen_y))
                        blitted = True
                except Exception:
                    pass

            if not blitted:
                color = EGA_BRIGHT_GREEN if is_active else EGA_BRIGHT_CYAN
                rect = pygame.Rect(screen_x + 1, screen_y + 1, TILE_SIZE - 2, TILE_SIZE - 2)
                pygame.draw.rect(surface, color, rect)
                char_label = str(p_idx + 1)
                txt = font.render(char_label, True, EGA_BLACK)
                surface.blit(txt, (screen_x + 4, screen_y + 1))

            # Highlight active member with yellow border
            if is_active:
                pygame.draw.rect(
                    surface,
                    EGA_YELLOW,
                    pygame.Rect(screen_x, screen_y, TILE_SIZE, TILE_SIZE),
                    1,
                )

    def _render_grid_fallback(self, surface: pygame.Surface) -> None:
        for y in range(COMBAT_HEIGHT):
            for x in range(COMBAT_WIDTH):
                rect = pygame.Rect(x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE)
                pygame.draw.rect(surface, EGA_DARK_GRAY, rect, 1)
