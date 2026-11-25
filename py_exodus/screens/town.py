"""City and castle exploration screen with NPC and vendor interactions."""
from __future__ import annotations

import random

from typing import TYPE_CHECKING, Any

import pygame

from py_exodus import debug
from py_exodus.aura import AuraType
from py_exodus.assets import MAP_ID_TO_LABEL
from py_exodus.combat.magic import prompt_cast_party
from py_exodus.constants import (
    Direction,
    Status,
    Transport,
)
from py_exodus.entities.party import PartyDeathException
from py_exodus.screens.base import BaseScreen
from py_exodus.screens.member_prompts import (
    prompt_hand,
    prompt_modify_order,
    prompt_ready_weapon,
    prompt_wear_armor,
    prompt_whose_item,
)
from py_exodus.screens.final import (
    apply_exodus_card_tiles,
    prompt_insert_card,
    safe_exodus,
)
from py_exodus.screens.vendor_dialog import start_vendor_dialog
from py_exodus import special_commands
from py_exodus.ui.renderer import WorldRenderer, can_move_to
from py_exodus.ui.stats_panel import StatsPanel
from py_exodus.ui.text_log import (
    EGA_BLACK,
    TextLog,
)
from py_exodus.world import doors as door_module
from py_exodus.world import portal_entry
from py_exodus.world import search as search_module
from py_exodus.world import realtime
from py_exodus.world import tile_effects

if TYPE_CHECKING:
    from py_exodus.assets import AssetManager
    from py_exodus.audio import AudioManager
    from py_exodus.entities.defs import VendorDef
    from py_exodus.entities.party import Party, PartyMember
    from py_exodus.world.map import GameMap, MapNpc


# Lord British's refusals (LairWare Messages 91, 263, 92, 93).
_LB_REFUSALS = {
    "experience": "Experience more!",
    "thanks": "Sosaria thanks you!",
    "no_more": "No more!",
    "mark": "Seek ye, the mark of kings!",
}



def town_combat_map_id(creature: Any, party_pos: tuple[int, int], game_map: Any) -> int:
    """LairWare BackGround (UltimaSpellCombat.c:774-810) for a town or castle
    fight: the party's tile picks the arena (floor C, grass G, ...)."""
    from py_exodus.screens.overworld import get_combat_map_id

    px, py = party_pos
    return get_combat_map_id(creature, px, py, px, py, Transport.FOOT, game_map)

class TownScreen(BaseScreen):
    """Town and castle navigation screen supporting NPC dialogues and vendor shopping."""

    def __init__(
        self,
        party: Party,
        map_id: int | str = 1,
        asset_mgr: AssetManager | None = None,
        audio: AudioManager | None = None,
        return_screen: BaseScreen | None = None,
        start_x: int | None = None,
        start_y: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(return_screen=return_screen, **kwargs)
        self.party = party
        self.map_id = map_id
        self.asset_mgr = asset_mgr
        self.audio = audio

        self.game_map: GameMap | None = None
        self._load_town_map()

        # Coordinates
        self.avatar_x = start_x if start_x is not None else 32
        self.avatar_y = start_y if start_y is not None else 60
        self.anim_frame = 0
        self.anim_timer = 0.0
        # Peer Gem (P) view state (Java PeerGemInputAdapter, see gem_view).
        self.gem_view_active = False

        self.world_renderer = (
            WorldRenderer(asset_mgr) if asset_mgr is not None else None
        )
        self.stats_panel = StatsPanel(asset_mgr=self.asset_mgr)
        self.text_log = TextLog(max_lines=5, wrap_width=64)

        # Town-local creature objects (e.g. horses spawned by the horse
        # vendor); Java keeps map creatures on the map object, not the save.
        self.creatures: list[dict[str, Any]] = []
        self._combat_npc: Any = None

        # Playtest-1 fix (item 3): Java logs "Entering " + Maps.getLabel()
        # + "!" (GameScreen.java:334) from the enum label table
        # (exodus/Constants.java:47-71); the maps.xml name attribute plays
        # no part (neither the Java nor the port XML has one). Map 3's enum
        # key is LCB, so the old .title() of GameMap.name printed
        # "Entering Lcb..." — the player-facing label is "Britain".
        game_map_id = getattr(self.game_map, "id", None)
        lookup_id: int | None = (
            int(game_map_id) if game_map_id is not None else None
        )
        label = (
            MAP_ID_TO_LABEL.get(lookup_id)
            if lookup_id is not None
            else None
        ) or str(getattr(self.game_map, "name", map_id)).title()
        self.text_log.add_message(f"Entering {label}!")
        self.text_log.add_message("Guards and citizens walk the streets.")

    def _load_town_map(self) -> None:
        if self.asset_mgr is None:
            return
        try:
            from py_exodus.world.loader import MapLoader

            loader = MapLoader(self.asset_mgr)
            loaded = loader.load_map(self.map_id)
            if hasattr(loaded, "width"):
                self.game_map = loaded
        except Exception:
            pass

    def on_enter(self) -> None:
        super().on_enter()
        self._play_town_music()
        # Restore cleared machine panels from exodusCardsStatus (GameScreen.java:299-311)
        apply_exodus_card_tiles(
            self.game_map, self.asset_mgr, getattr(self.party, "exodus_cards_status", 0)
        )
        # LairWare Enter (UltimaMain.c:1515-1517): Castle Exodus after the
        # fall is SafeExodus'd on every entry.
        if getattr(self.party, "exodus_defeated", 0):
            safe_exodus(self.game_map, self.asset_mgr)

    def _play_town_music(self) -> None:
        if self.audio is None:
            return
        m_id = str(self.map_id).lower()
        if m_id in ("1", "british", "castle"):
            self.audio.play_music("fanfare")
        elif m_id in ("2", "7", "10", "exodus", "devil", "death"):
            self.audio.play_music("exodus")
        else:
            self.audio.play_music("towns")

    def get_current_map_coords(self) -> tuple[int, int]:
        """Party-standing tile in this town (Java GameScreen.getCurrentMapCoords)."""
        return (self.avatar_x, self.avatar_y)

    def add_creature(self, creature: dict[str, Any]) -> None:
        """Add a map creature object (Java Map.addCreature)."""
        self.creatures.append(creature)

    def board(self, x: int, y: int) -> None:
        """Board a transport object on the tile (Java GameScreen.java:945-979)."""
        if self.party.transport != Transport.FOOT:
            self.text_log.add_message("Board: Can't!")
            return

        # Frigate object on the party's exact tile
        # Only this map's objects: a ship parked on Sosaria at the same
        # coordinates is not here (user ruling 2026-11-22).
        objs = self.party.objects_on(self.game_map)
        for idx, obj in enumerate(objs):
            tile = str(obj.get("tile", "")).lower()
            # Java matches the exact tile name: `"frigate".equals(
            # d.getTile().getName())` (GameScreen.java:955) — no "ship"
            # superset ("ship" is not a tile name Java can match).
            if tile == "frigate" and obj.get("x") == x and obj.get("y") == y:
                objs.pop(idx)
                self.party.transport = Transport.SHIP
                self.party.last_ship = obj
                if self.audio is not None:
                    self.audio.play_sfx("trigger")
                self.text_log.add_message("Board Frigate!")
                return

        # Horse creature on the party's exact tile
        for creature in self.creatures:
            if (
                str(creature.get("tile", "")).lower() == "horse"
                and creature.get("x") == x
                and creature.get("y") == y
            ):
                self.creatures.remove(creature)
                self.party.transport = Transport.HORSE
                if self.audio is not None:
                    self.audio.play_sfx("trigger")
                self.text_log.add_message("Mount Horse!")
                return

        self.text_log.add_message("Board What?")

    def handle_event(self, event: pygame.event.Event) -> None:
        # Mouse wheel scrolls the shared text log back through history
        # (Java LogScrollPane affordance). The peer-gem view owns all input,
        # so the wheel neither scrolls nor closes it (GameScreen.java:1146-1152).
        if event.type == pygame.MOUSEWHEEL:
            if not self.gem_view_active:
                self.text_log.handle_wheel(event)
            return

        if event.type != pygame.KEYDOWN:
            return

        # Java PeerGemInputAdapter.keyUp (GameScreen.java:1146-1152): the
        # gem view owns all input; any key closes it and restores the timer
        # with no turn passing.
        if self.gem_view_active:
            self.gem_view_active = False
            return

        if self.text_log.is_waiting_for_input:
            self.text_log.handle_event(event)
            self._settle_letter_turn()
            return

        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): debug cheat
        # harness (GBC cheat.c:768-825 docheat) — F10 opens the cheat menu in
        # --debug mode only; non-debug F10 stays inert.
        if debug.DEBUG_MODE and event.key == pygame.K_F10:
            debug.open_cheat_menu(self.text_log, self.party)
            return

        # PageUp/PageDown always scroll the text log back (arrow keys scroll
        # only inside the log's own prompt handling, when they cannot act as
        # direction/command answers).
        if self.text_log.handle_scroll_key(event.key):
            return

        # Movement: Arrow keys and Keypad ONLY (no WASD)
        # LairWare main loop (UltimaMain.c:1057-1059): ``LetterCommand();
        # Routine6E35();`` -- every letter ends the turn once, whatever the
        # command did; _settle_letter_turn adds it when the command didn't.
        if pygame.K_a <= event.key <= pygame.K_z:
            self._letter_turn = (self.party.moves, self.map_id)
        if event.key in (pygame.K_UP, pygame.K_KP8):
            self._try_move(Direction.NORTH)
        elif event.key in (pygame.K_DOWN, pygame.K_KP2):
            self._try_move(Direction.SOUTH)
        elif event.key in (pygame.K_LEFT, pygame.K_KP4):
            self._try_move(Direction.WEST)
        elif event.key in (pygame.K_RIGHT, pygame.K_KP6):
            self._try_move(Direction.EAST)
        elif event.key == pygame.K_SPACE:
            # Java GameScreen.java:624-628 — the pass key finishes the turn
            # at the party's tile (ticks + standing effect). Towns drain the
            # submorsels pool at 10 per turn (non-surface map).
            self.text_log.add_message("Pass")  # Java GameScreen.java:626-627
            # No standing tile effect: LairWare burns only on the step onto
            # lava (ValidDir, UltimaMain.c:3194-3207).
            self._finish_turn(None)
        # Town commands:
        elif event.key == pygame.K_a:
            self._prompt_attack()
        elif event.key == pygame.K_b:
            # Java GameScreen.java:578-580 + 945-979 — B is board(v.x, v.y) on
            # every GameScreen map ("Board: Can't!" mounted, transport scan,
            # else "Board What?"), then the keyUp tail consumes a turn.
            self.board(self.avatar_x, self.avatar_y)
            self._consume_pass_turn()
        elif event.key == pygame.K_c:
            self._prompt_cast()
        elif event.key == pygame.K_e:
            # E works on every map incl. towns (Java GameScreen.java:538-556).
            self._enter_portal()
        elif event.key == pygame.K_g:
            self._get_chest()
        elif event.key == pygame.K_h:
            self._prompt_hand_equipment()
        elif event.key == pygame.K_j:
            self._join_gold()
        elif event.key == pygame.K_l:
            self._open()
        elif event.key == pygame.K_m:
            self._prompt_modify_order()
        elif event.key == pygame.K_n:
            self._negate_time()
        elif event.key == pygame.K_o:
            self._prompt_other()
        elif event.key == pygame.K_p:
            # Java GameScreen.java:604-605 — P runs peerGem() and falls
            # through the keyUp tail (GameScreen.java:628), so the press
            # consumes a turn either way, before the view opens.
            self._peer_gem()
        elif event.key == pygame.K_q:
            # Java GameScreen.java:557-563 — Q is the save command on every
            # GameScreen map; only SOSARIA (id 0) accepts it, so towns always
            # refuse. The key has no early return and consumes a turn.
            self.text_log.add_message("Cannot save here!")
            self._consume_pass_turn()
        elif event.key == pygame.K_r:
            self._prompt_ready_weapon()
        elif event.key == pygame.K_s:
            self._search()
        elif event.key == pygame.K_t:
            self._prompt_talk()
        elif event.key == pygame.K_u:
            self._unlock()
        elif event.key == pygame.K_v:
            if self.audio is not None:
                self.audio.enabled = not self.audio.enabled
                msg = "Sound & Music ENABLED." if self.audio.enabled else "Sound & Music MUTED."
                self.text_log.add_message(f"Volume: {msg}")
            # Java GameScreen.java:615-622 — V has no early return; consumes a turn.
            self._consume_pass_turn()
        elif event.key == pygame.K_w:
            self._prompt_wear_armor()
        elif event.key == pygame.K_x:
            # X only dismounts to FOOT; leaving a town is border-walking only
            # (Java GameScreen.java:584-596). The key has no early return in
            # Java — every X press consumes a turn.
            self._exit_transport()
            self._consume_pass_turn()
        elif event.key == pygame.K_y:
            self._prompt_yell()
        elif event.key == pygame.K_z:
            self._toggle_zstats()
        else:
            # Java GameScreen.keyUp tail (GameScreen.java:628): keys without an
            # explicit early return — including unhandled D, I and K — fall
            # through to finishTurn with no message.
            self._consume_pass_turn()
        self._settle_letter_turn()

    def _settle_letter_turn(self) -> None:
        """Once a letter command's prompts are done, take its turn if the
        command didn't (LairWare Routine6E35 after every LetterCommand,
        UltimaMain.c:1057-1059)."""
        mark = getattr(self, "_letter_turn", None)
        if mark is None or self.text_log.is_waiting_for_input:
            return
        self._letter_turn = None
        moves, map_id = mark
        # A command that left the map (Enter, a whirlpool) already set the
        # new one up; its turn is not replayed there. A command that pushed
        # a screen (a fight, a town, the Final screen) is not given a turn
        # underneath it: LW runs Routine6E35 only once the fight is over,
        # and a turn here would move the next attacker into a second fight.
        pushed = self.manager is not None and self.manager.current_screen is not self
        if self.is_finished or pushed or self.party.moves != moves or self.map_id != map_id:
            return
        self._consume_pass_turn()

    def _prompt_attack(self) -> None:
        """LairWare Attack (UltimaMain.c:1329-1340): a direction, then
        whoever stands there is fought (AttackCode); nobody -> NotHere."""

        def _on_dir(d_str: str) -> None:
            d = Direction.from_name_or_key(d_str)
            if d is None:
                self.text_log.add_message("Invalid direction!")
                return
            npc = self._find_npc_at(self.avatar_x + d.dx, self.avatar_y + d.dy)
            if npc is None:
                self.text_log.add_message("Not Here!")
                self._consume_pass_turn()
                return
            self._start_exodus_combat(npc)

        self.text_log.prompt("Attack Direction? (N,S,E,W):", callback=_on_dir, single_char=True)

    def _consume_pass_turn(self) -> None:
        """Java GameScreen.keyUp tail (GameScreen.java:628): finishTurn on the
        party's tile with no message (unhandled keys and fall-throughs).
        No standing tile effect (LairWare ValidDir, UltimaMain.c:3194-3207)."""
        self._finish_turn(None)

    def _toggle_zstats(self) -> None:
        """Cycle Ztats inspect mode through party members."""
        current = self.stats_panel.inspect_index
        member_count = len(self.party.members)
        if member_count == 0:
            return
        if current is None:
            self.stats_panel.inspect_index = 0
        elif current + 1 < member_count:
            self.stats_panel.inspect_index = current + 1
        else:
            self.stats_panel.inspect_index = None

        if self.stats_panel.inspect_index is not None:
            m = self.party.members[self.stats_panel.inspect_index]
            self.text_log.add_message(f"Zstats: {m.name} ({m.profession.name})")
            cur_w = m.weapon.name if hasattr(m.weapon, "name") else str(m.weapon)
            cur_a = m.armor.name if hasattr(m.armor, "name") else str(m.armor)
            self.text_log.add_message(f"Readied: {cur_w}  Worn: {cur_a}")
            wpn_list = [f"{wt.name}:{cnt}" for wt, cnt in m.weapons.items() if cnt > 0]
            arm_list = [f"{at.name}:{cnt}" for at, cnt in m.armors.items() if cnt > 0]
            if wpn_list:
                self.text_log.add_message("Weapons: " + ", ".join(wpn_list))
            if arm_list:
                self.text_log.add_message("Armors: " + ", ".join(arm_list))
        else:
            self.text_log.add_message("Zstats: Normal view")
        # Java GameScreen.java:564-572 — Z has no early return; consumes a turn.
        self._consume_pass_turn()

    def _try_move(self, direction: Direction) -> None:
        if self.game_map is None:
            return

        nx = self.avatar_x + direction.dx
        ny = self.avatar_y + direction.dy

        # Check exit border. LairWare Routine6E35 (UltimaMisc.c:1365-1369)
        # leaves a town once a step lands on column 0 or row 0; a step off
        # the far edge wraps to 0 (MapConstrain) over the grass GetXYVal
        # reads beyond a town map (UltimaMisc.c:982-992), so it leaves too.
        # Either way the leaving step is a turn (Routine6E35 IncMoves).
        if not (0 <= nx < self.game_map.width and 0 <= ny < self.game_map.height):
            self._finish_turn(None)
            if not self.party.is_party_dead():
                self._exit_town()
            return

        if self.map_id == 2:
            hostile = next(
                (
                    npc
                    for npc in self.game_map.npcs
                    if npc.x == nx
                    and npc.y == ny
                    and getattr(npc, "movement", None) == "ATTACK_AVATAR"
                ),
                None,
            )
            if hostile is not None:
                self._start_exodus_combat(hostile)
                return

        if can_move_to(self.game_map, nx, ny, transport=Transport.FOOT, party=self.party):
            # Java exploration movement is never slowed (slowedByTile's only
            # caller is CombatScreen.java:937) — no speed roll on town moves.
            self.avatar_x = nx
            self.avatar_y = ny
            if self.audio is not None:
                self.audio.play_sfx("walk_normal")
            # LairWare ValidDir (UltimaMain.c:3194-3207) burns on the step
            # ONTO lava, so the effect is the entered tile's, on a move only.
            self._finish_turn(self.game_map.get_tile(nx, ny))
            if (nx == 0 or ny == 0) and not self.party.is_party_dead():
                self._exit_town()  # Routine6E35, UltimaMisc.c:1365-1369
        else:
            # LairWare ValidDir (UltimaMain.c:3178-3192), user ruling
            # 2026-11-25 (T-05): the first unmarked living member takes 99;
            # passage only when every living member is marked. The validator
            # fires in ANY context, so the town-blocked energy-field entry
            # strikes too (british/exodus/death carry energy cells); a wipe
            # routes through check_party_death like _finish_turn.
            try:
                tile_effects.apply_force_field_strike(
                    self.party,
                    self.game_map.get_tile(nx, ny),
                    self.text_log.add_message,
                )
            except PartyDeathException:
                pass
            if self.check_party_death():
                return
            if self.audio is not None:
                self.audio.play_sfx("blocked")
            # A refused step still takes the turn: LairWare's NoGo, then the
            # main loop's Routine6E35 (UltimaMain.c:1057-1091, 1203-1215).
            self._finish_turn(None)

    def _start_exodus_combat(self, npc: Any) -> None:
        """Battle a hostile ATTACK_AVATAR person (any town; LW AttackCode)."""
        # LairWare Combat ($7FB0, UltimaSpellCombat.c:873-876): every fight
        # first sets HPMON 0xC0 (attack) for each guard (0x48, tile 18) and
        # Lord British (0x4C, tile 19) in the monster table, whoever started
        # it. They hunt the party for the rest of the visit (towns reset on
        # entry). User ruling 2026-11-25 (ledger B-15): exactly LairWare.
        if self.game_map is not None:
            for person in self.game_map.npcs:
                if getattr(person, "tile_index", -1) in (18, 19):
                    person.movement = "ATTACK_AVATAR"
        if self.asset_mgr is None:
            return
        from py_exodus.screens.combat_screen import CombatScreen
        from py_exodus.world.loader import MapLoader

        self._combat_npc = npc
        cname = str(getattr(npc, "tile_name", getattr(npc, "tile", "orc")) or "orc").lower()
        c_def = self.asset_mgr.get_creature(cname)
        c_map = MapLoader(self.asset_mgr).load_conflict_map(
            town_combat_map_id(c_def or cname, (self.avatar_x, self.avatar_y), self.game_map)
        )
        # LairWare HowMany ($80DE, UltimaSpellCombat.c:812-824): guards come 8
        # (`gMonType == 0x24`), Castle Exodus fights 8, and any other town or
        # castle fight -- a merchant, Lord British -- is one on one (returns
        # 0). User ruling 2026-11-25 (ledger B-09).
        from py_exodus.combat.arena import EXODUS_MAP_ID

        map_id = getattr(self.game_map, "id", 2)
        one_on_one = cname != "guard" and map_id != EXODUS_MAP_ID
        combat_scr = CombatScreen(
            party=self.party,
            combat_map=c_map,
            creature_tile=cname,
            asset_mgr=self.asset_mgr,
            audio=self.audio,
            return_screen=self,
            manager=self.manager,
            context_map_id=map_id,
            monster_count=1 if one_on_one else None,
        )
        if self.manager is not None:
            self.manager.push_screen(combat_scr)
        else:
            self.next_screen = combat_scr
            self.is_finished = True

    def end_combat(self, is_won: bool) -> None:
        """Remove the defeated town person when returning from CombatScreen.

        LairWare AttackCode (UltimaMain.c:1342-1352) turns the person's tile
        into a chest (0x24) unless it stood on water; the chest stays in the
        town until the visit ends (towns reset on entry)."""
        npc = self._combat_npc
        if (
            is_won
            and npc is not None
            and self.game_map is not None
            and npc in self.game_map.npcs
        ):
            self.game_map.npcs.remove(npc)
            under = self.game_map.get_tile(npc.x, npc.y)
            chest = self.asset_mgr.tile_defs_by_name.get("chest") if self.asset_mgr else None
            if chest is not None and str(getattr(under, "name", "")).lower() != "water":
                self.game_map.set_tile(npc.x, npc.y, chest)
        self._combat_npc = None

    def _finish_turn(self, effect_tile=None) -> None:
        """End the town turn: LairWare Routine6E35 (UltimaMisc.c:1357-1401):
        IncMoves and AgeChars (every 4th call here, Party[3] > 0; the moons
        stand still off Sosaria), the tile effect, the castle gate and the
        Exodus fireball, then FinishAll's people moves."""
        try:
            self.party.end_turn(sosaria=False)
            tile_effects.apply_rule_effect(self.party, effect_tile)
            self._moon_step()
            self._exodus_castle_ball()
        except PartyDeathException:
            pass
        self.check_party_death()
        if not self.party.is_party_dead():
            self._move_people()

    def _moon_step(self) -> None:
        """LairWare Routine6E35 (UltimaMisc.c:1375-1377) and HandleMoonStep
        off Sosaria (UltimaMisc.c:1579-1585): standing on a gate tile (136;
        Castle British and Castle Exodus have them) sends the party to a
        random tile of the map whose value is 4 (grass, nobody on it):
        ``xpos = RandNum(0, gCurMapSize - 1); ypos = RandNum(0, gCurMapSize -
        1);`` until it is."""
        gm = self.game_map
        if gm is None:
            return
        tile = gm.get_tile(self.avatar_x, self.avatar_y)
        if str(getattr(tile, "name", "")).lower() != "moongate":
            return
        while True:
            x = random.randint(0, gm.width - 1)
            y = random.randint(0, gm.height - 1)
            t = gm.get_tile(x, y)
            if str(getattr(t, "name", "")).lower() != "grass":
                continue
            if any(n.x == x and n.y == y for n in gm.npcs):
                continue
            break
        self.avatar_x, self.avatar_y = x, y
        if self.audio is not None:
            self.audio.play_sfx("moongate_flash")

    def _exodus_castle_ball(self) -> None:
        """LairWare Routine6E35 (UltimaMisc.c:1379-1398) with ExodusCastle
        (UltimaSpellCombat.c:672-684): every turn in Castle Exodus, until
        Exodus falls, time stop is cancelled and a ball lands on a random tile
        of the 12x12 view (RandNum(0, 11) twice); on the party's own (5,5) it
        is BombTrap (UltimaMain.c:1728-1740): each living member loses
        (RandNum(0, 255) & 0x77) + 8 (zp[0x13] is never set, so +8)."""
        if self.map_id != 2 or self.party.exodus_defeated:
            return
        if self.party.aura.get_type() == AuraType.QUICKNESS:
            self.party.aura.set(AuraType.NONE, 0)  # gTimeNegate = 0
        xs = random.randint(0, 11)
        ys = random.randint(0, 11)
        if (xs, ys) != (5, 5):
            return
        self.text_log.add_message("A fireball strikes the party!")
        for m in list(self.party.members):
            if m.is_disabled():  # BombTrap: CheckAlive members only
                continue
            if self.audio is not None:
                self.audio.play_sfx("Hit.wav")
            m.apply_damage((random.randint(0, 255) & 0x77) + 8)

    # LW ValidMonsterDir (UltimaMisc.c:263-272): land people walk only on
    # grass/brush/forest/floor (tile values 4/8/12/32); sea people (pirate,
    # serpent, squid) only on water.
    _PEOPLE_LAND_TILES = frozenset({"grass", "brush", "forest", "floor"})
    _PEOPLE_SEA = frozenset({"pirate", "serpent", "squid"})

    @staticmethod
    def _lw_heading(value: int) -> int:
        """LW GetHeading (UltimaMisc.c:444-452) for a 0-255 roll."""
        if value == 0:
            return 0
        return 1 if value <= 127 else -1

    def _person_can_step(self, npc: Any, x: int, y: int) -> bool:
        gm = self.game_map
        if not (0 <= x < gm.width and 0 <= y < gm.height):
            return False
        tile = gm.get_tile(x, y)
        name = str(getattr(tile, "name", "")).lower()
        kind = str(getattr(npc, "tile_name", getattr(npc, "tile", "")) or "").lower()
        if kind in self._PEOPLE_SEA:
            ok = name == "water"
        else:
            ok = name in self._PEOPLE_LAND_TILES
        if not ok:
            return False
        return not any(o is not npc and o.x == x and o.y == y for o in gm.npcs)

    def _move_people(self) -> None:
        """LW MoveMonsters, town/castle branch (UltimaMisc.c:1191-1330):
        every turn each person acts on its behaviour (ctrl & 0xC0):
        FIXED never moves; WANDER takes a random diagonal-ish step half the
        time; FOLLOW_AVATAR steps toward the party; ATTACK_AVATAR steps
        toward the party and, when that step would land on the party
        (any of the 8 neighbours), starts the battle (AttackCode removes it
        from the map). A blocked diagonal tries the vertical step, then the
        horizontal one (move7AAA); nobody steps onto the party."""
        # FinishAll (UltimaMisc.c:1120-1125), from Routine6E35 in towns too:
        # while time is stopped (gTimeNegate) nobody moves, and the count
        # drops a turn.
        if self.party.aura.get_type() == AuraType.QUICKNESS:
            self.party.aura.pass_turn()
            return
        gm = self.game_map
        if gm is None or not gm.npcs:
            return
        px, py = self.avatar_x, self.avatar_y
        for npc in list(reversed(gm.npcs)):
            if npc not in gm.npcs:
                continue
            mv = getattr(npc, "movement", "FIXED")
            if mv == "WANDER":
                if random.randrange(256) < 128:
                    continue
                dx = self._lw_heading(random.randrange(256))
                xs = npc.x + dx
                if xs <= 0:
                    continue
                dy = self._lw_heading(random.randrange(256))
                ys = npc.y + dy
                if ys <= 0:
                    continue
            elif mv in ("FOLLOW_AVATAR", "ATTACK_AVATAR"):
                dx = (px > npc.x) - (px < npc.x)
                dy = (py > npc.y) - (py < npc.y)
                if mv == "ATTACK_AVATAR" and (npc.x + dx, npc.y + dy) == (px, py):
                    self._start_exodus_combat(npc)
                    return
            else:
                continue
            for cx, cy in ((npc.x + dx, npc.y + dy), (npc.x, npc.y + dy), (npc.x + dx, npc.y)):
                if (cx, cy) == (npc.x, npc.y):
                    continue
                if self._person_can_step(npc, cx, cy):
                    if (cx, cy) != (px, py):
                        npc.x, npc.y = cx, cy
                    break

    def _exit_town(self) -> None:
        self.text_log.add_message("Leaving city...")
        if self.party.map_id == 1 or str(self.map_id) in ("1", "british", "castle"):
            self.party.map_id = 0
            self.party.x = 45
            self.party.y = 18
        self.exit_screen()

    def _prompt_talk(self) -> None:
        def _on_member(m_str: str) -> None:
            s = m_str.strip()
            if not s or not s.isdigit():
                self.text_log.add_message("Nobody selected!")
                return
            idx = int(s) - 1
            if not (0 <= idx < len(self.party.members)):
                self.text_log.add_message("Nobody selected!")
                return
            speaker = self.party.members[idx]
            # LairWare Transact (UltimaMain.c:2302-2305): a living member only.
            if speaker.is_disabled():
                self.text_log.add_message("Incapacitated!")
                return

            def _on_dir(d_str: str) -> None:
                d = Direction.from_name_or_key(d_str)
                if d is None:
                    self.text_log.add_message("Invalid direction!")
                    return
                self._talk_to_direction(d, speaker=speaker)

            self.text_log.prompt("Direction? (N,S,E,W):", callback=_on_dir, single_char=True)

        self.text_log.prompt("TALK> Which party member? (1-4):", callback=_on_member, single_char=True)

    def _talk_to_direction(self, direction: Direction, speaker: PartyMember | None = None) -> None:
        if self.game_map is None:
            return

        if speaker is None and self.party.active_member is not None:
            speaker = self.party.active_member

        tx = self.avatar_x + direction.dx
        ty = self.avatar_y + direction.dy

        # Java SecondaryInputProcessor.java:163-179 — only a `signs` rule tile
        # steps the gaze one further: the vendor sits behind its sign. There
        # is no counter widening and no unconditional second-step fallback.
        adj_tile = self.game_map.get_tile(tx, ty)
        if adj_tile is not None and getattr(adj_tile, "rule", "") == "signs":
            tx += direction.dx
            ty += direction.dy

        npc = self._find_npc_at(tx, ty)

        if npc is None:
            self.text_log.add_message("Funny, no response!")
            return

        tile_name = str(getattr(npc, "tile_name", getattr(npc, "tile", ""))).lower()
        npc_name = str(getattr(npc, "name", "")).lower()

        # Check Lord British
        if (
            "british" in tile_name
            or "british" in npc_name
            or npc_name == "lord british"
            or getattr(npc, "tile_index", -1) == 19
        ):
            self._interact_lord_british(speaker)
            return

        # Check Vendor
        vendor = self._find_vendor_at(npc)
        if vendor is not None:
            self._start_vendor_shopping(vendor, buyer=speaker)
            return

        # Standard dialogue
        conv = getattr(npc, "conversation", None)
        if conv:
            self.text_log.add_message(f'"{conv}"')
        else:
            self.text_log.add_message("Funny, no response!")

    def _find_npc_at(self, x: int, y: int) -> MapNpc | None:
        if self.game_map is None:
            return None
        for npc in self.game_map.npcs:
            if npc.x == x and npc.y == y:
                return npc
        return None

    def _find_vendor_at(self, npc: MapNpc) -> VendorDef | None:
        if getattr(npc, "vendor", None) is not None:
            return npc.vendor
        if self.asset_mgr is None:
            return None
        v = self.asset_mgr.get_vendor(self.map_id, npc.x, npc.y)
        if v is None and hasattr(npc, "start_x") and hasattr(npc, "start_y"):
            v = self.asset_mgr.get_vendor(self.map_id, npc.start_x, npc.start_y)
        if v is None and hasattr(npc, "name"):
            # Check by name
            v = self.asset_mgr.vendors.get(npc.name.lower())
        return v

    def _interact_lord_british(self, speaker: PartyMember | None = None) -> None:
        """Handle Lord British: level advance of the talking member only.

        Java truth: ``exodus/SecondaryInputProcessor.java:190-197`` — visiting
        Lord British calls ``meetLordBritish()`` on the *talking* member and
        logs either "Thou hast been advanced!" or "Welcome my child..
        Experience more!". There is NO resurrection here: Java's resurrect
        loop in ``ConversationDialog.java:133-160`` is commented out.
        """
        target = speaker
        if target is None:
            target = self.party.active_member
        if target is None:
            self.text_log.add_message("Lord British says:\n'Welcome my child..\nExperience more!'")
            return

        exodus_defeated = bool(getattr(self.party, "exodus_defeated", 0))
        reason = target.character.lord_british_refusal(exodus_defeated)
        if reason is None and target.character.meet_lord_british(exodus_defeated):
            self.text_log.add_message("Lord British says:\n'Thou hast been advanced!'")
            if self.audio is not None:
                self.audio.play_sfx("magic")
        else:
            # LairWare Transact (UltimaMain.c:2357-2380): messages 91, 263, 92, 93.
            text = _LB_REFUSALS.get(reason or "experience")
            self.text_log.add_message(f"Lord British says:\n'Welcome my child..\n{text}'")

    def _start_vendor_shopping(self, vendor: VendorDef, buyer: PartyMember | None = None) -> None:
        """Interactive shopping dialog stream with vendor via TextLog."""
        if self.audio is not None:
            self.audio.play_music("shopping")

        # Per-class vendor dialogs (Java VendorClassSet.getVendorImpl,
        # vendor/VendorClassSet.java:58-94): FOOD, TAVERNINFO, ORACLEINFO and
        # HORSE run dedicated state machines; not-yet-ported classes fall
        # through to the generic menu below.
        shopper = buyer or self.party.active_member
        if shopper is not None and start_vendor_dialog(
            vendor,
            shopper,
            self.text_log,
            screen=self,
            on_end=self._play_town_music,
        ):
            return

        self.text_log.add_message(f"Welcome to {vendor.name}!")
        self.text_log.add_message(f"Owner: {vendor.owner}")

        # Show catalog — full list (Task 8: the items[:6] truncation is gone;
        # e.g. Dawn's Windsor Weaponry sells 14 weapons, vendor.xml b..o).
        if vendor.items:
            for item in vendor.items:
                self.text_log.add_message(f"{item.choice}) {item.name} - {item.price}gp")

        def _on_choice(choice: str) -> None:
            c = choice.strip().lower()
            if not c or c == "bye":
                self.text_log.add_message("Good journey to thee!")
                self._play_town_music()
                return

            item = vendor.get_item(c)
            if item is None:
                self.text_log.add_message("We have no such ware.")
                self._play_town_music()
                return

            if self.party.gold < item.price:
                self.text_log.add_message("Thou cannot afford that!")
            else:
                self.party.gold -= item.price
                active = buyer or self.party.active_member
                qty = getattr(item, "quantity", 1) or 1
                g_type = (getattr(item, "guild_item_type", "") or "").lower()
                i_type = (getattr(item, "item_type", "") or "").lower()
                h_type = (getattr(item, "heal_type", "") or "").lower()
                name_l = getattr(item, "name", "").lower()

                if item.weapon_type and active is not None:
                    active.character.weapons[item.weapon_type] = active.character.weapons.get(item.weapon_type, 0) + 1
                    self.text_log.add_message(f"Bought {item.name}! Added to inventory.")
                elif item.armor_type and active is not None:
                    active.character.armors[item.armor_type] = active.character.armors.get(item.armor_type, 0) + 1
                    self.text_log.add_message(f"Bought {item.name}! Added to inventory.")
                elif "torch" in g_type or "torch" in name_l:
                    self.party.torches += qty
                    self.text_log.add_message(f"Bought {qty} Torches! Added to pack.")
                elif "gem" in g_type or "gem" in name_l:
                    self.party.gems += qty
                    self.text_log.add_message(f"Bought {qty} Gems! Added to pack.")
                elif "key" in g_type or "key" in name_l:
                    self.party.keys += qty
                    self.text_log.add_message(f"Bought {qty} Keys! Added to pack.")
                elif "powder" in g_type or "powder" in name_l:
                    self.party.powder += qty
                    self.text_log.add_message(f"Bought {qty} Powder! Added to pack.")
                elif "food" in i_type or "food" in name_l or "ration" in name_l:
                    food_gain = qty * 25 if qty <= 5 else qty
                    self.party.food += food_gain
                    self.text_log.add_message(f"Bought {food_gain} food rations!")
                elif "horse" in i_type or "horse" in name_l:
                    self.party.transport = Transport.HORSE
                    self.text_log.add_message("Thou dost mount a fine steed! (Transport is now Horse)")
                elif h_type or "heal" in name_l or "cure" in name_l or "resurrect" in name_l:
                    if active is not None:
                        if "cure" in h_type or "cure" in name_l:
                            active.character.status = Status.GOOD
                            self.text_log.add_message(f"{active.name} has been cured of poison!")
                        elif "resurrect" in h_type or "resurrect" in name_l:
                            # LairWare UltimaMisc.c:1766-1767: only 'D' -> 'G',
                            # HP left as it was (as PartyMember.heal RESURRECT).
                            active.character.status = Status.GOOD
                            self.text_log.add_message(f"{active.name} has been resurrected!")
                        else:
                            active.character.hp = active.character.max_hp
                            self.text_log.add_message(f"{active.name} has been fully healed!")
                else:
                    self.text_log.add_message(f"Bought {item.name}!")
                if self.audio is not None:
                    self.audio.play_sfx("trigger")

            self._play_town_music()

        self.text_log.prompt(
            "What wouldst thou buy? (Choice):",
            callback=_on_choice,
            single_char=True,
            on_cancel=self._play_town_music,
        )

    def _open(self) -> None:
        """L = OPEN with a direction (Java SIP:212-219 + BaseMap.openDoor)."""
        self.text_log.prompt(
            "OPEN> Direction? (N,S,E,W):",
            callback=self._parse_and_open,
            single_char=True,
        )

    def _parse_and_open(self, d_str: str) -> None:
        d = Direction.from_name_or_key(d_str)
        if d is None:
            self.text_log.add_message("Invalid direction!")
            return
        if self.game_map is None:
            self.text_log.add_message("Can't!")
            return
        if door_module.open_door(self.game_map, self.avatar_x + d.dx, self.avatar_y + d.dy):
            self.text_log.add_message("Opened!")
        else:
            self.text_log.add_message("Can't!")

    def _unlock(self) -> None:
        """UNLOCK: a member 1-4 unlocks a chosen direction with one of their
        keys (Java SIP:221-238 — ``member.getPlayer().keys > 0 &&
        bm.unlockDoor(x, y)``, then ``keys--``)."""
        def _on_member(m_str: str) -> None:
            member = self._parse_member(m_str)
            if member is None:
                self.text_log.add_message("Nobody selected!")
                return
            self.text_log.prompt(
                "Direction? (N,S,E,W):",
                callback=lambda d_str: self._unlock_direction(d_str, member),
                single_char=True,
            )

        self.text_log.prompt("UNLOCK> Which party member? (1-4):", callback=_on_member, single_char=True)

    def _unlock_direction(self, d_str: str, member) -> None:
        d = Direction.from_name_or_key(d_str)
        if d is None:
            self.text_log.add_message("Invalid direction!")
            return
        if d in (Direction.NORTH, Direction.SOUTH):
            # LairWare Unlock (UltimaMain.c:2400-2408): doors open only east
            # or west (``(ys != ypos) && (xs == xpos)`` is NotHere).
            self.text_log.add_message("Not Here!")
            return
        if self.game_map is None:
            self.text_log.add_message("Can't!")
            return
        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): unlocking consumes one key (GBC menucmd2.c:1595-1650)
        # — the acting member is the member 1-4 the U flow already prompts for,
        # and unlock_door itself checks its keys and spends one ONLY on the
        # locked-door conversion (GBC menucmd2.c:1655-1657; anything else is
        # dounlock's else: no conversion, no spend). A keyless
        # member is refused with "You need a key!" (GBC refusal message).
        if door_module.unlock_door(
            self.game_map, self.avatar_x + d.dx, self.avatar_y + d.dy, member=member
        ):
            self.text_log.add_message("Unlocked!")
        else:
            if getattr(member, "keys", 0) <= 0:
                self.text_log.add_message("You need a key!")
            else:
                self.text_log.add_message("Can't!")

    def _parse_member(self, who_str: str):
        """Resolve a 1-4 member prompt answer to a PartyMember (or None)."""
        try:
            idx = int(who_str.strip()) - 1
            return self.party.get_member(idx)
        except ValueError:
            return None

    def _get_chest(self) -> None:
        """GET: pick the opening member, then check ONLY the party's own tile
        (fix round 2 — final ruling).

        Java truth: ``exodus/SecondaryInputProcessor.java:126-160, 308-318`` —
        x/y is a per-event local copy and the G branch fires only on a member
        digit, with unshifted currentX/currentY: the chest under the party's
        feet IS the openable chest (GameScreen.java:1036-1074, chest *tile*
        fallback at the same coordinates, replaced with floor). Non-digit
        input logs NOTHING; the keydown still consumes a turn (SIP:459 passes
        the party's tile, so the tile-rule effect uses it).
        """
        from py_exodus.assets import TileDef
        from py_exodus.world.chests import (
            ChestNotFound,
            open_chest,
            take_chest_object,
        )

        def _on_who(who_str: str) -> None:
            member = self._parse_member(who_str)
            if member is None:
                # Non-digits fall through silently (Java), but the keydown
                # still consumes the turn at the party's tile (SIP:459).
                self._finish_turn(None)  # no standing effect (LW ValidDir)
                return
            # LairWare GetChest (UltimaMain.c:1600-1603): the opener must be
            # alive (CheckAlive: good or poisoned), else "Incapacitated!".
            if member.is_disabled():
                self.text_log.add_message("Incapacitated!")
                self._finish_turn(None)
                return

            px, py = self.avatar_x, self.avatar_y
            try:
                take_chest_object(self.party, px, py, self.game_map)
            except ChestNotFound:
                # Java getChest: a chest *tile* under the party is replaced
                # with floor (GameScreen.java:1069-1071).
                tile = self.game_map.get_tile(px, py) if self.game_map else None
                if tile is None or getattr(tile, "rule", "") != "chest":
                    self.text_log.add_message("Not Here!")
                    self._finish_turn(None)  # no standing effect (LW ValidDir)
                    return
                self.game_map.set_tile(px, py, TileDef(index=3, name="floor"))

            # Task 2 death flow: a chest trap (gas) can leave the whole party
            # dead; route game over (Java GameScreen.java:444-446 partyDeath
            # → start screen). The chests pipeline does not currently raise —
            # the try/except is future-proofing for later tasks routing it
            # through PartyMember.apply_damage; the post-check covers both.
            try:
                for line in open_chest(self.party, member):
                    self.text_log.add_message(line)
            except PartyDeathException:
                pass
            self.check_party_death()
            self._finish_turn(None)  # no standing effect (LW ValidDir)

        self.text_log.prompt("GET> Which party member? (1-4):", callback=_on_who, single_char=True)

    def _peer_gem(self) -> None:
        """PEER AT GEM: LairWare PeerGem (UltimaMain.c:2143-2159) asks whose
        gem; that member spends one and the map shows. The turn passes
        either way; closing the view costs none."""
        from py_exodus.ui.gem_view import PEER_MESSAGE

        def _spent(_member) -> None:
            self.text_log.add_message(PEER_MESSAGE)
            self.gem_view_active = True

        prompt_whose_item(
            self.text_log, self.party, "PEER> Whose gem? (1-4):", "gems",
            _spent, turn_callback=self._consume_pass_turn,
        )

    def _prompt_cast(self) -> None:
        """Cast non-combat spells while in town."""
        prompt_cast_party(
            self.text_log,
            self.party,
            world_map=self.game_map,
            audio=self.audio,
            view_callback=self._show_vieda_view,
            # The town tile under the avatar (APPAR UNEM opens the chest
            # there); party.x/y still hold the overworld entrance.
            position=(self.avatar_x, self.avatar_y),
        )

    def _show_vieda_view(self) -> None:
        """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): VIEDA renders the
        peer-gem view (GBC menucmd.c:1379-1390; LW UltimaSpellCombat.c
        corroboration) — town-site GBC casts route through the same
        dopeergem(1) as any other non-battle site, and the town already owns
        the full gem-view machinery (own Peer Gem state, render override). The
        spell branch skips the choosechar2/gem decrement (menucmd.c:695-712
        runs only for dopeergem(0)), so no gem and no turn is paid by the
        view itself; the overworld's identical handler is
        OverworldScreen._show_vieda_view."""
        # The view owns input; the render override draws the gem picture.
        self.gem_view_active = True

    def _prompt_hand_equipment(self) -> None:
        """LairWare HandEquip (UltimaMain.c:1744-1944): food, gold,
        supplies, a weapon or an armour (member_prompts.prompt_hand). The
        turn passes at the press (Java GameScreen.java:574-576)."""
        self._consume_pass_turn()
        prompt_hand(self.text_log, self.party)

    def _join_gold(self) -> None:
        """JOIN GOLD: prompt a member 1-4 and pool every purse into theirs.

        Java truth: ``exodus/SecondaryInputProcessor.java:271-277`` — the J key
        logs ``JOIN GOLD> To party member? (1-4)`` and calls
        ``Party.poolGold(index)``; nothing is logged.
        """
        self.text_log.prompt(
            "JOIN GOLD> To party member? (1-4):",
            callback=self._pool_to_member,
            single_char=True,
        )

    def _pool_to_member(self, who_str: str) -> None:
        member = self._parse_member(who_str)
        if member is None:
            return  # non-digits fall through silently (Java)
        self.party.pool_gold(self.party.members.index(member))

    def _negate_time(self) -> None:
        """NEGATE TIME: LairWare NegateTime (UltimaMain.c:2122-2139) asks
        whose powder; that member spends one and time stops for 10 turns
        (gTimeNegate = 10)."""

        def _spent(_member) -> None:
            self.text_log.add_message("Stop time with a powder!")
            self.party.aura.set(AuraType.QUICKNESS, 10)

        prompt_whose_item(
            self.text_log, self.party, "NEGATE TIME> Whose powder? (1-4):", "powder",
            _spent, turn_callback=self._consume_pass_turn,
        )

    def _search(self) -> None:
        """SEARCH: a member 1-4 searches the party's tile (Java SIP:240-250
        with ``BaseMap.searchLocation`` — labels, else "Nothing here!")."""
        def _on_who(who_str: str) -> None:
            member = self._parse_member(who_str)
            if member is None:
                self.text_log.add_message("Invalid member #!")
                return
            desc = search_module.search_location(
                self.game_map, self.party, member, self.avatar_x, self.avatar_y
            )
            if desc is not None:
                self.text_log.add_message(f"You found {desc}.")
            else:
                self.text_log.add_message("Nothing here!")

        self.text_log.prompt("SEARCH> Which party member? (1-4):", callback=_on_who, single_char=True)

    def _enter_portal(self) -> None:
        """Enter a portal on the party's tile (Java GameScreen.java:538-556 —
        E is available on every map including towns)."""
        if self.game_map is None:
            return
        if not portal_entry.enter_portal(self, self.avatar_x, self.avatar_y):
            # Java GameScreen.java:538-556 — no portal on the tile: E falls
            # through SILENTLY to the keyUp tail, which consumes the turn.
            self._consume_pass_turn()

    def _exit_transport(self) -> None:
        """X only dismounts to FOOT, dropping the ridden transport on the
        tile (Java GameScreen.java:584-596); leaving a town is border-walking
        only."""
        # Java GameScreen.java:584-596 — X is silent on foot (it only resets
        # the transport and sets the avatar anim); the keyUp tail still ticks.
        if self.party.transport == Transport.FOOT:
            return

        old_t = self.party.transport
        # LairWare Exit (UltimaMain.c:2523-2538): only on water or grass.
        tile = self.game_map.get_tile(self.avatar_x, self.avatar_y) if self.game_map else None
        if tile is None or getattr(tile, "index", 99) > 1:
            self.text_log.add_message("Not Here!")
            return
        self.party.transport = Transport.FOOT
        # A transport left in a town stays with the town (which reloads),
        # never in the surface map's list at the town's coordinates (user
        # ruling 2026-11-22: nothing parked on one map shows on another).
        objs = self.party.objects_on(self.game_map)
        if old_t == Transport.HORSE:
            objs.append({"tile": "horse", "x": self.avatar_x, "y": self.avatar_y})
            self.text_log.add_message("Dismounted horse.")
        else:
            existing = next(
                (
                    obj
                    for obj in objs
                    if str(obj.get("tile", "")).lower() == "frigate"
                    and obj.get("x") == self.avatar_x
                    and obj.get("y") == self.avatar_y
                ),
                None,
            )
            if existing is None:
                ship = {"tile": "frigate", "x": self.avatar_x, "y": self.avatar_y}
                objs.append(ship)
            else:
                ship = existing
            self.party.last_ship = ship
            self.text_log.add_message("Disembarked frigate.")

    def _prompt_other(self) -> None:
        """Prompt for custom other command (PRAY, BRIBE, STEAL, DIG, etc.).

        USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): functional Other
        command (GBC menucmd3.c:1019-1236; menucmd2.c:1440-1540; LW
        UltimaMisc.c:2262-2503) — both this and the overworld prompt delegate
        to py_exodus.special_commands so the commands share one
        implementation. KISS is NOT in U3 (K is Klimb; the LW menu lacks it
        too — user ruling 2026-11-14): it falls through to the generic
        "Nothing happened.".
        """
        self.text_log.prompt("Other Command? ", callback=self._run_other)

    def _run_other(self, cmd: str) -> None:
        """One Other word (LairWare OtherCommand, UltimaMisc.c:2262-2510);
        Yell runs the same words (Yell(0) is OtherCommand(1))."""
        c = cmd.strip().upper()
        if not c:
            return
        if c == "PRAY":
            self.text_log.add_message(
                special_commands.do_pray(
                    self.avatar_x,
                    self.avatar_y,
                    self.map_id,
                    str(getattr(self.game_map, "name", "") or ""),
                )
            )
        elif c == "BRIBE":
            special_commands.bribe_flow(
                self.text_log,
                self.party,
                self.avatar_x,
                self.avatar_y,
                self.game_map,
                creatures=self.creatures,
            )
        elif c == "STEAL":
            special_commands.steal_flow(
                self.text_log, self.party, self.avatar_x, self.avatar_y, self.game_map
            )
        elif c == "DIG":
            special_commands.dig_flow(
                self.text_log, self.party, self.avatar_x, self.avatar_y, self.game_map
            )
        elif c == "SEARCH":
            special_commands.search_flow(
                self.text_log, self.party, self.avatar_x, self.avatar_y, self.game_map
            )
        elif c == "SCORE":
            self.text_log.add_message(special_commands.do_score(self.party))
        elif c == "INSERT":
            prompt_insert_card(self, self.avatar_x, self.avatar_y)
        else:
            self.text_log.add_message(f"'{c}': Nothing happened.")

    def _prompt_modify_order(self) -> None:
        """Modify marching order (Java BaseScreen.java:165-204
        NewOrderInputAdapter; GameScreen keeps the corrected "exchange #")."""
        prompt_modify_order(self.text_log, self.party, turn_callback=self._consume_pass_turn)

    def _prompt_ready_weapon(self) -> None:
        """Ready Weapon via the shared member flow (Java GameScreen.java:
        608-613 SIP -> ReadyWearInputAdapter; "Success!"/"Failed!")."""
        prompt_ready_weapon(self.text_log, self.party, self.asset_mgr, turn_callback=self._consume_pass_turn)

    def _prompt_wear_armor(self) -> None:
        """Wear Armor via the shared member flow (Java GameScreen.java:
        608-613 SIP -> ReadyWearInputAdapter; "Success!"/"Failed!")."""
        prompt_wear_armor(self.text_log, self.party, self.asset_mgr, turn_callback=self._consume_pass_turn)

    def _prompt_yell(self) -> None:
        """YELL: a member 1-4, then a word (Java SIP:252-260 + YellInputAdapter
        522-577 — EVOCARE next to snake tiles, gated on marks[2])."""
        def _on_member(m_str: str) -> None:
            member = self._parse_member(m_str)
            if member is None:
                self.text_log.add_message("Nobody selected!")
                return
            # Java SecondaryInputProcessor.java:535-538: empty ENTER keeps the
            # prompt open, while ESC remains available so keyboard players cannot softlock.
            self.text_log.prompt(
                "Yell what? ",
                callback=lambda phrase: self._yell(member, phrase),
                allow_empty=False,
            )

        self.text_log.prompt("YELL> Which party member? (1-4):", callback=_on_member, single_char=True)

    def _yell(self, member, phrase: str) -> None:
        """LairWare Yell (UltimaMain.c:2544-2590): EVOCARE, with the Mark of
        Snake, carries the party three rows past the Great Earth Serpent
        (a serpent tile 236 north, or 232 south); the serpent stays. Any
        other word is an Other command (Yell(0) is OtherCommand(1))."""
        word = phrase.strip().upper()
        if not word:
            return
        if word != "EVOCARE":
            self._run_other(word)
            return
        if member.is_disabled():
            self.text_log.add_message("Incapacitated!")  # OtherCommand CheckAlive
            return
        if getattr(member, "marks", [0, 0, 0, 0])[2] <= 0:  # Mark of Snake
            self.text_log.add_message("No effect.")
            return
        gm = self.game_map
        x, y = self.avatar_x, self.avatar_y

        def _index(tx: int, ty: int) -> int:
            tile = gm.get_tile(tx, ty) if gm else None
            return getattr(tile, "index", -1)

        oy = y
        if _index(x, y - 1) == 59:  # snake2, LW tile value 236
            oy -= 3
        if _index(x, y + 1) == 58:  # snake1, LW tile value 232
            oy += 3
        if oy == y:
            self.text_log.add_message("No effect.")
            return
        if self.audio is not None:
            self.audio.play_sfx("rocks")
        self.avatar_y = oy

    def update(self, dt: float) -> None:
        # LairWare DoWind (UltimaMain.c:3284-3300) keeps time in towns too:
        # gUpdateWhere is 3 there, so every 5/60 s GetKeyMouse poll runs
        # FullUpdate (:3469-3470). The Peer Gem picture stops it.
        if not self.gem_view_active:
            realtime.advance_wind(self.party, dt)
        self.anim_timer += dt
        if self.anim_timer >= 0.2:
            self.anim_timer = 0.0
            self.anim_frame = (self.anim_frame + 1) % 16  # LW scrolls water in 16 steps

    def render(self, surface: pygame.Surface) -> None:
        surface.fill(EGA_BLACK)
        w, h = surface.get_width(), surface.get_height()

        # Peer Gem view (Java PeerGemInputAdapter): the gem picture replaces
        # the whole screen (GameScreen.java:1119-1129); the port drops to a
        # plain colored-cell map, see py_exodus/ui/gem_view.py.
        if self.gem_view_active and self.game_map is not None:
            from py_exodus.ui.gem_view import render_gem_view

            marks = [(npc.x, npc.y) for npc in self.game_map.npcs]
            marks.extend((c["x"], c["y"]) for c in self.creatures)
            render_gem_view(surface, self.game_map, self.avatar_x, self.avatar_y, marks=marks)
            return

        scale = 3 if w >= 640 else 1
        v_size = 176 * scale

        if scale > 1:
            temp_v = pygame.Surface((176, 176))
            if self.world_renderer is not None and self.game_map is not None:
                self.world_renderer.render_viewport(
                    temp_v,
                    self.game_map,
                    center_x=self.avatar_x,
                    center_y=self.avatar_y,
                    anim_frame=self.anim_frame,
                    party=self.party,
                    dest_pos=(0, 0),
                    avatar_x=self.avatar_x,
                    avatar_y=self.avatar_y,
                    avatar_override="ranger",
                )
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
            if self.world_renderer is not None and self.game_map is not None:
                self.world_renderer.render_viewport(
                    surface,
                    self.game_map,
                    center_x=self.avatar_x,
                    center_y=self.avatar_y,
                    anim_frame=self.anim_frame,
                    party=self.party,
                    dest_pos=(0, 0),
                    avatar_x=self.avatar_x,
                    avatar_y=self.avatar_y,
                    avatar_override="ranger",
                )

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
