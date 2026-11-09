"""City and castle exploration screen with NPC and vendor interactions."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pygame

from py_exodus.aura import AuraType
from py_exodus.combat.magic import prompt_cast_party
from py_exodus.constants import (
    Direction,
    Status,
    Transport,
)
from py_exodus.entities.party import PartyDeathException
from py_exodus.screens.base import BaseScreen
from py_exodus.screens.member_prompts import (
    prompt_modify_order,
    prompt_ready_weapon,
    prompt_wear_armor,
)
from py_exodus.screens.final import (
    apply_exodus_card_tiles,
    prompt_insert_card,
)
from py_exodus.screens.vendor_dialog import start_vendor_dialog
from py_exodus.ui.renderer import WorldRenderer, can_move_to
from py_exodus.ui.stats_panel import StatsPanel
from py_exodus.ui.text_log import (
    EGA_BLACK,
    TextLog,
)
from py_exodus.world import doors as door_module
from py_exodus.world import portal_entry
from py_exodus.world import search as search_module
from py_exodus.world import tile_effects

if TYPE_CHECKING:
    from py_exodus.assets import AssetManager
    from py_exodus.audio import AudioManager
    from py_exodus.entities.defs import VendorDef
    from py_exodus.entities.party import Party, PartyMember
    from py_exodus.world.map import GameMap, MapNpc


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
        self.text_log = TextLog(max_lines=5, wrap_width=28)

        # Town-local creature objects (e.g. horses spawned by the horse
        # vendor); Java keeps map creatures on the map object, not the save.
        self.creatures: list[dict[str, Any]] = []

        town_name = getattr(self.game_map, "name", str(map_id)).title()
        self.text_log.add_message(f"Entering {town_name}...")
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
        for idx, obj in enumerate(self.party.dynamic_objects):
            tile = str(obj.get("tile", "")).lower()
            if tile in ("frigate", "ship") and obj.get("x") == x and obj.get("y") == y:
                self.party.dynamic_objects.pop(idx)
                self.party.transport = Transport.SHIP
                if self.party.last_ship is not obj:
                    self.party.adjust_ship_hull(50)
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
            return

        # Movement: Arrow keys and Keypad ONLY (no WASD)
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
            self._finish_turn(self.game_map.get_tile(self.avatar_x, self.avatar_y) if self.game_map else None)
        # Town commands:
        elif event.key == pygame.K_a:
            self.text_log.add_message("Attack: The guards eye thee suspiciously! Peace reigns here.")
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

    def _consume_pass_turn(self) -> None:
        """Java GameScreen.keyUp tail (GameScreen.java:628): finishTurn on the
        party's tile with no message (unhandled keys and fall-throughs)."""
        self._finish_turn(self.game_map.get_tile(self.avatar_x, self.avatar_y) if self.game_map else None)

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

        # Check exit border
        if not (0 <= nx < self.game_map.width and 0 <= ny < self.game_map.height):
            self._exit_town()
            return

        start_tile = self.game_map.get_tile(self.avatar_x, self.avatar_y)

        if can_move_to(self.game_map, nx, ny, transport=Transport.FOOT, party=self.party):
            # Java exploration movement is never slowed (slowedByTile's only
            # caller is CombatScreen.java:937) — no speed roll on town moves.
            self.avatar_x = nx
            self.avatar_y = ny
            if self.audio is not None:
                self.audio.play_sfx("walk_normal")
            self._finish_turn(start_tile)
        else:
            if self.audio is not None:
                self.audio.play_sfx("blocked")

    def _finish_turn(self, effect_tile=None) -> None:
        """End the town movement turn: submorsel tick, aura tick, then the
        standing tile effect (Java GameScreen.finishTurn GameScreen.java:
        706-754 — endTurn, then aura.passTurn). Towns drain submorsels at 10
        per move (non-surface map)."""
        try:
            self.party.end_turn(surface=False)
            self.party.aura.pass_turn()
            tile_effects.apply_rule_effect(self.party, effect_tile)
        except PartyDeathException:
            pass
        self.check_party_death()

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

        if target.character.meet_lord_british():
            self.text_log.add_message("Lord British says:\n'Thou hast been advanced!'")
            if self.audio is not None:
                self.audio.play_sfx("magic")
        else:
            self.text_log.add_message("Lord British says:\n'Welcome my child..\nExperience more!'")

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
                            active.character.status = Status.GOOD
                            active.character.hp = active.character.max_hp
                            self.text_log.add_message(f"{active.name} has been resurrected!")
                        else:
                            active.character.hp = active.character.max_hp
                            self.text_log.add_message(f"{active.name} has been fully healed!")
                else:
                    self.text_log.add_message(f"Bought {item.name}!")
                if self.audio is not None:
                    self.audio.play_sfx("trigger")

            self._play_town_music()

        self.text_log.prompt("What wouldst thou buy? (Choice):", callback=_on_choice, single_char=True)

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
        if self.game_map is None:
            self.text_log.add_message("Can't!")
            return
        if getattr(member, "keys", 0) > 0 and door_module.unlock_door(
            self.game_map, self.avatar_x + d.dx, self.avatar_y + d.dy
        ):
            self.text_log.add_message("Unlocked!")
            member.keys -= 1
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
                self._finish_turn(
                    self.game_map.get_tile(self.party.x, self.party.y)
                    if self.game_map else None
                )
                return

            px, py = self.avatar_x, self.avatar_y
            try:
                take_chest_object(self.party, px, py)
            except ChestNotFound:
                # Java getChest: a chest *tile* under the party is replaced
                # with floor (GameScreen.java:1069-1071).
                tile = self.game_map.get_tile(px, py) if self.game_map else None
                if tile is None or getattr(tile, "rule", "") != "chest":
                    self.text_log.add_message("Not Here!")
                    self._finish_turn(
                        self.game_map.get_tile(px, py) if self.game_map else None
                    )
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
            self._finish_turn(self.game_map.get_tile(px, py) if self.game_map else None)

        self.text_log.prompt("GET> Which party member? (1-4):", callback=_on_who, single_char=True)

    def _peer_gem(self) -> None:
        """Peer into a mystical gem to view the map.

        Java truth: GameScreen.java:1076-1087 — peerGem() picks the FIRST
        member holding gems (no member prompt), decrements that member, logs
        "Peer at a Gem!" and swaps input to PeerGemInputAdapter (map view,
        timer paused, GameScreen.java:1114-1152); with none it logs
        "Thou dost have no gems!". P itself (GameScreen.java:604-605) is a
        GameScreen branch, so towns run it and then the keyUp tail consumes
        the turn.
        """
        from py_exodus.ui.gem_view import (
            NO_GEMS_MESSAGE,
            PEER_MESSAGE,
            consume_peer_gem,
        )

        if consume_peer_gem(self.party) is not None:
            self.text_log.add_message(PEER_MESSAGE)
            self.gem_view_active = True
        else:
            self.text_log.add_message(NO_GEMS_MESSAGE)
        self._consume_pass_turn()

    def _prompt_cast(self) -> None:
        """Cast non-combat spells while in town."""
        prompt_cast_party(self.text_log, self.party, world_map=self.game_map, audio=self.audio)

    def _prompt_hand_equipment(self) -> None:
        """Hand an unequipped weapon or armor item between party members."""
        self._consume_pass_turn()  # Java GameScreen.java:574-576: H falls through
        if len(self.party.members) < 2:
            self.text_log.add_message("Hand Equipment: Need at least 2 members!")
            return

        def _on_from(from_str: str) -> None:
            try:
                p1 = int(from_str.strip()) - 1
            except ValueError:
                self.text_log.add_message("Invalid member #!")
                return
            if not (0 <= p1 < len(self.party.members)):
                self.text_log.add_message("Invalid member #!")
                return

            def _on_to(to_str: str) -> None:
                try:
                    p2 = int(to_str.strip()) - 1
                except ValueError:
                    self.text_log.add_message("Invalid member #!")
                    return
                if not (0 <= p2 < len(self.party.members)) or p1 == p2:
                    self.text_log.add_message("Invalid recipient!")
                    return

                m1 = self.party.members[p1]
                m2 = self.party.members[p2]

                # Java HandDialog.java:114-146 — the ">" button transfers the
                # selected unequipped weapon or armor (count decrement /
                # increment); there is no gold transfer and an empty selection
                # only plays the BLOCKED sound.
                transferred = False
                for w, cnt in list(m1.weapons.items()):
                    if cnt > 0 and w != m1.weapon:
                        m1.weapons[w] -= 1
                        m2.weapons[w] = m2.weapons.get(w, 0) + 1
                        self.text_log.add_message(f"{m1.name} handed {w.name} to {m2.name}.")
                        transferred = True
                        break

                if not transferred:
                    for a, cnt in list(m1.armors.items()):
                        if cnt > 0 and a != m1.armor:
                            m1.armors[a] -= 1
                            m2.armors[a] = m2.armors.get(a, 0) + 1
                            self.text_log.add_message(f"{m1.name} handed {a.name} to {m2.name}.")
                            transferred = True
                            break
                    # No gold fallback: Java HandDialog transfers equipment
                    # only (HandDialog.java:114-146).

            self.text_log.prompt("To member #? (1-4): ", callback=_on_to, single_char=True)

        self.text_log.prompt("Hand Equipment: From member #? (1-4): ", callback=_on_from, single_char=True)

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
        """NEGATE TIME: consume the FIRST member's powder for a 6-turn
        QUICKNESS aura (Java GameScreen.java:1089-1100 negateTime)."""
        for m in self.party.members:
            if getattr(m, "powder", 0) > 0:
                m.powder -= 1
                self.text_log.add_message("Stop time with a powder!")
                self.party.aura.set(AuraType.QUICKNESS, 6)
                self._consume_pass_turn()  # Java keyUp tail: N falls through
                return
        self.text_log.add_message("None!")
        self._consume_pass_turn()  # Java keyUp tail: N falls through

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
        self.party.transport = Transport.FOOT
        if old_t == Transport.HORSE:
            self.party.dynamic_objects.append({"tile": "horse", "x": self.avatar_x, "y": self.avatar_y})
            self.text_log.add_message("Dismounted horse.")
        else:
            ship = {"tile": "frigate", "x": self.avatar_x, "y": self.avatar_y}
            self.party.dynamic_objects.append(ship)
            self.party.last_ship = ship
            self.text_log.add_message("Disembarked frigate.")

    def _prompt_other(self) -> None:
        """Prompt for custom other command (PRAY, BRIBE, STEAL, DIG, etc.)."""
        def _on_other(cmd: str) -> None:
            c = cmd.strip().upper()
            if not c:
                return
            if c == "PRAY":
                if str(self.map_id) in ("10", "yew") and 44 <= self.avatar_x <= 52 and 44 <= self.avatar_y <= 52:
                    self.text_log.add_message("A vision appears: Yell 'EVOCARE'!")
                else:
                    self.text_log.add_message("A calmness and silence of the soul.")
            elif c == "BRIBE":
                self.text_log.add_message("The guards glare at thee: 'Bribe us not!'")
            elif c == "STEAL":
                self.text_log.add_message("Thou art caught in the act! 'Thief!'")
            elif c == "DIG":
                self.text_log.add_message("Cobblestones are too hard to dig here.")
            elif c == "KISS":
                self.text_log.add_message("A citizen smiles and waves.")
            elif c == "INSERT":
                prompt_insert_card(self, self.avatar_x, self.avatar_y)
            else:
                self.text_log.add_message(f"'{c}': Nothing happened.")

        self.text_log.prompt("Other Command? ", callback=_on_other)

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
            self.text_log.prompt(
                "Yell what? ",
                callback=lambda phrase: self._yell(member, phrase),
            )

        self.text_log.prompt("YELL> Which party member? (1-4):", callback=_on_member, single_char=True)

    def _yell(self, member, phrase: str) -> None:
        word = phrase.strip().upper()
        if not word:
            return
        if word != "EVOCARE":
            self.text_log.add_message("What?")
            return

        gm = self.game_map

        def _is_snake(x: int, y: int) -> bool:
            tile = gm.get_tile(x, y) if gm else None
            return tile is not None and str(getattr(tile, "name", "")).startswith("snake")

        if not (_is_snake(self.avatar_x, self.avatar_y - 1) or _is_snake(self.avatar_x, self.avatar_y + 1)):
            self.text_log.add_message("No effect.")
            return

        if getattr(member, "marks", [0, 0, 0, 0])[2] > 0:  # Mark of Snake (SIP:546)
            if self.audio is not None:
                self.audio.play_sfx("rocks")
            # Java YellInputAdapter replaces the fixed serpent tiles with
            # water (SIP:548-549).
            self._replace_tile("water", 10, 57)
            self._replace_tile("water", 10, 58)
        else:
            if self.audio is not None:
                self.audio.play_sfx("negative_effect")
            self.text_log.add_message("No effect.")

    def _replace_tile(self, name: str, x: int, y: int) -> None:
        """Java ``GameScreen.replaceTile`` — swap the map tile for `name`."""
        if self.game_map is None:
            return
        tile = None
        if self.asset_mgr is not None:
            tile = self.asset_mgr.get_tile_by_name(name)
        if tile is None:
            from py_exodus.assets import TileDef

            tile = TileDef(index=2, name=name)
        self.game_map.set_tile(x, y, tile)

    def update(self, dt: float) -> None:
        self.anim_timer += dt
        if self.anim_timer >= 0.2:
            self.anim_timer = 0.0
            self.anim_frame = (self.anim_frame + 1) % 4

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
            self.stats_panel.render(
                surface,
                self.party,
                rect=pygame.Rect(v_size, 0, w - v_size, h),
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

            self.stats_panel.render(
                surface,
                self.party,
                rect=pygame.Rect(176, 0, w - 176, h),
            )

            log_h = max(24, h - 176)
            self.text_log.render(
                surface,
                rect=pygame.Rect(0, 176, 176, log_h),
                draw_border=True,
            )
