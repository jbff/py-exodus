"""City and castle exploration screen with NPC and vendor interactions."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pygame

from py_exodus.combat.magic import prompt_cast_party
from py_exodus.constants import (
    ArmorType,
    Direction,
    Status,
    TileAttrib,
    Transport,
    WeaponType,
)
from py_exodus.screens.base import BaseScreen
from py_exodus.ui.renderer import WorldRenderer, can_move_to
from py_exodus.ui.stats_panel import StatsPanel
from py_exodus.ui.text_log import (
    EGA_BLACK,
    TextLog,
)

if TYPE_CHECKING:
    from py_exodus.assets import AssetManager
    from py_exodus.audio import AudioManager
    from py_exodus.entities.defs import VendorDef
    from py_exodus.entities.party import Party
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

        self.world_renderer = (
            WorldRenderer(asset_mgr) if asset_mgr is not None else None
        )
        self.stats_panel = StatsPanel()
        self.text_log = TextLog(max_lines=5, wrap_width=28)

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

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
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
            self.text_log.add_message("Pass.")
        # Town commands:
        elif event.key == pygame.K_a:
            self.text_log.add_message("Attack: The guards eye thee suspiciously! Peace reigns here.")
        elif event.key == pygame.K_b:
            self.text_log.add_message("Board: No transport vessels within city walls.")
        elif event.key == pygame.K_c:
            self._prompt_cast()
        elif event.key == pygame.K_g:
            self.text_log.add_message("Get: No chest here!")
        elif event.key == pygame.K_h:
            self._prompt_hand_equipment()
        elif event.key == pygame.K_i:
            self._ignite_torch()
        elif event.key == pygame.K_j:
            self.party.pool_gold(0)
            self.text_log.add_message(f"All gold gathered into party pool: {self.party.gold} GP.")
        elif event.key == pygame.K_l:
            self._prompt_door(open_door=True)
        elif event.key == pygame.K_m:
            self._prompt_modify_order()
        elif event.key == pygame.K_n:
            self.text_log.add_message("Negate time: None owned!")
        elif event.key == pygame.K_o:
            self._prompt_other()
        elif event.key == pygame.K_p:
            if self.party.gems > 0:
                self.party.gems -= 1
                self.text_log.add_message(f"Gem vision: {getattr(self.game_map, 'name', 'Town')} survey at ({self.avatar_x}, {self.avatar_y}).")
            else:
                self.text_log.add_message("Peer: None owned!")
        elif event.key == pygame.K_q:
            self.text_log.add_message("Quit: Cannot save in town! Journey outside or see Lord British.")
        elif event.key == pygame.K_r:
            self._prompt_ready_weapon()
        elif event.key == pygame.K_s:
            self.text_log.add_message("Search: Thou searchest the cobblestones... Nothing here.")
        elif event.key == pygame.K_t:
            self._prompt_talk()
        elif event.key == pygame.K_u:
            self._prompt_door(open_door=False)
        elif event.key == pygame.K_v:
            if self.audio is not None:
                self.audio.enabled = not self.audio.enabled
                msg = "Sound & Music ENABLED." if self.audio.enabled else "Sound & Music MUTED."
                self.text_log.add_message(f"Volume: {msg}")
        elif event.key == pygame.K_w:
            self._prompt_wear_armor()
        elif event.key == pygame.K_x:
            self._exit_town()
        elif event.key == pygame.K_y:
            self._prompt_yell()
        elif event.key == pygame.K_z:
            self._toggle_zstats()

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

    def _try_move(self, direction: Direction) -> None:
        if self.game_map is None:
            return

        nx = self.avatar_x + direction.dx
        ny = self.avatar_y + direction.dy

        # Check exit border
        if not (0 <= nx < self.game_map.width and 0 <= ny < self.game_map.height):
            self._exit_town()
            return

        if can_move_to(self.game_map, nx, ny, transport=Transport.FOOT, party=self.party):
            self.avatar_x = nx
            self.avatar_y = ny
            if self.audio is not None:
                self.audio.play_sfx("walk_normal")
        else:
            if self.audio is not None:
                self.audio.play_sfx("blocked")

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

        # Check if the adjacent tile is a sign / counter tile
        adj_tile = self.game_map.get_tile(tx, ty)
        if adj_tile is not None and (
            getattr(adj_tile, "rule", "") == "signs"
            or 36 <= getattr(adj_tile, "index", -1) <= 57
        ):
            # Step behind sign / counter to reach the vendor
            tx += direction.dx
            ty += direction.dy

        npc = self._find_npc_at(tx, ty)
        if npc is None:
            # Fallback: check 1 tile further in case of speaking across a counter or sign
            npc = self._find_npc_at(self.avatar_x + direction.dx * 2, self.avatar_y + direction.dy * 2)

        # Check vendor directly at target location if no NPC was matched
        if npc is None and self.asset_mgr is not None:
            direct_vendor = self.asset_mgr.get_vendor(self.map_id, tx, ty)
            if direct_vendor is None:
                direct_vendor = self.asset_mgr.get_vendor(
                    self.map_id, self.avatar_x + direction.dx * 2, self.avatar_y + direction.dy * 2
                )
            if direct_vendor is not None:
                self._start_vendor_shopping(direct_vendor, buyer=speaker)
                return

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
        """Handle Lord British character level advancements and resurrection."""
        revived_any = False
        for pm in self.party.members:
            if pm.status in (Status.DEAD, Status.ASHES):
                pm.status = Status.GOOD
                pm.hp = pm.max_hp
                revived_any = True

        if revived_any:
            self.text_log.add_message("Lord British says: 'Thou art resurrected!'")
            if self.audio is not None:
                self.audio.play_sfx("magic")

        advanced_any = False
        if speaker is not None:
            if speaker.character.meet_lord_british():
                advanced_any = True
        else:
            for member in self.party.members:
                if member.character.meet_lord_british():
                    advanced_any = True

        if advanced_any:
            self.text_log.add_message("Lord British says:\n'Thou hast been advanced!'")
            if self.audio is not None:
                self.audio.play_sfx("magic")
        elif not revived_any:
            self.text_log.add_message("Lord British says:\n'Welcome my child..\nExperience more!'")

    def _start_vendor_shopping(self, vendor: VendorDef, buyer: PartyMember | None = None) -> None:
        """Interactive shopping dialog stream with vendor via TextLog."""
        if self.audio is not None:
            self.audio.play_music("shopping")

        self.text_log.add_message(f"Welcome to {vendor.name}!")
        self.text_log.add_message(f"Owner: {vendor.owner}")

        # Show catalog
        if vendor.items:
            for item in vendor.items[:6]:
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

    def _prompt_door(self, open_door: bool) -> None:
        def _on_dir(d_str: str) -> None:
            d = Direction.from_name_or_key(d_str)
            if d is None:
                self.text_log.add_message("Invalid direction!")
                return
            self._handle_door(d, open_door)

        action_name = "Open" if open_door else "Unlock"
        self.text_log.prompt(f"{action_name} door: Direction? (N,S,E,W):", callback=_on_dir, single_char=True)

    def _handle_door(self, direction: Direction, open_door: bool) -> None:
        if self.game_map is None:
            return
        tx = self.avatar_x + direction.dx
        ty = self.avatar_y + direction.dy
        tile = self.game_map.get_tile(tx, ty)
        if tile is None:
            self.text_log.add_message("Nothing there!")
            return

        attribs = getattr(tile, "attribs", TileAttrib.NONE)
        if bool(attribs & (TileAttrib.DOOR | TileAttrib.LOCKEDDOOR)):
            # Replace door tile with floor/unblocked
            replacement = getattr(self.game_map, "default_floor", tile)
            self.game_map.set_tile(tx, ty, replacement)
            self.text_log.add_message("Door opened!")
            if self.audio is not None:
                self.audio.play_sfx("trigger")
        else:
            self.text_log.add_message("No door there!")

    def _prompt_cast(self) -> None:
        """Cast non-combat spells while in town."""
        prompt_cast_party(self.text_log, self.party, world_map=self.game_map, audio=self.audio)

    def _prompt_hand_equipment(self) -> None:
        """Hand equipment between party members."""
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
                transferred = False
                for w, cnt in list(m1.weapons.items()):
                    if cnt > 0 and w != m1.weapon:
                        m1.weapons[w] -= 1
                        m2.weapons[w] = m2.weapons.get(w, 0) + 1
                        self.text_log.add_message(f"{m1.name} handed {w.name} to {m2.name}.")
                        transferred = True
                        break

                if not transferred:
                    if m1.gold >= 10:
                        m1.gold -= 10
                        m2.gold += 10
                        self.text_log.add_message(f"{m1.name} handed 10 gold to {m2.name}.")
                    else:
                        self.text_log.add_message(f"{m1.name} has no spare equipment for {m2.name}.")

            self.text_log.prompt("To member #? (1-4): ", callback=_on_to, single_char=True)

        self.text_log.prompt("Hand Equipment: From member #? (1-4): ", callback=_on_from, single_char=True)

    def _ignite_torch(self) -> None:
        """Light a torch."""
        if self.party.torches > 0:
            self.party.torches -= 1
            self.party.torch_duration += 100
            self.text_log.add_message("Torch ignited! Area is illuminated.")
        else:
            self.text_log.add_message("None owned!")

    def _prompt_modify_order(self) -> None:
        """Modify marching order of party."""
        if len(self.party.members) < 2:
            self.text_log.add_message("Modify Order: Need at least 2 members!")
            return

        def _on_first(p1_str: str) -> None:
            try:
                p1 = int(p1_str.strip()) - 1
            except ValueError:
                self.text_log.add_message("Invalid member #!")
                return
            if not (0 <= p1 < len(self.party.members)):
                self.text_log.add_message("Invalid member #!")
                return

            def _on_second(p2_str: str) -> None:
                try:
                    p2 = int(p2_str.strip()) - 1
                except ValueError:
                    self.text_log.add_message("Invalid member #!")
                    return
                if not (0 <= p2 < len(self.party.members)):
                    self.text_log.add_message("Invalid member #!")
                    return

                m1 = self.party.members[p1]
                m2 = self.party.members[p2]
                self.party.swap_members(p1, p2)
                self.text_log.add_message(f"Order modified: {m1.name} and {m2.name} swapped.")

            self.text_log.prompt("With member #? (1-4): ", callback=_on_second, single_char=True)

        self.text_log.prompt("Modify Order: Exchange member #? (1-4): ", callback=_on_first, single_char=True)

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
            else:
                self.text_log.add_message(f"'{c}': Nothing happened.")

        self.text_log.prompt("Other Command? ", callback=_on_other)

    def _prompt_ready_weapon(self) -> None:
        """Equip weapon on selected party member with A-P selection and inventory tracking."""
        def _on_member(m_str: str) -> None:
            try:
                idx = int(m_str.strip()) - 1
            except ValueError:
                self.text_log.add_message("Invalid member #!")
                return
            m = self.party.get_member(idx)
            if m is None:
                self.text_log.add_message("Invalid member #!")
                return

            weapon_types = list(WeaponType)
            self.text_log.add_message(f"-- Ready Weapon for {m.name} --")
            for w_idx, wt in enumerate(weapon_types):
                letter = chr(ord('A') + w_idx)
                if wt == WeaponType.NONE:
                    self.text_log.add_message(f"{letter} - Hands")
                    continue
                cnt = m.weapons.get(wt, 0)
                is_equipped = (m.weapon == wt)
                if cnt > 0 or is_equipped:
                    status_tag = " (readied)" if is_equipped else f" ({cnt})"
                    self.text_log.add_message(f"{letter} - {wt.name.capitalize()}{status_tag}")

            def _on_weap(w_code: str) -> None:
                c = w_code.strip().upper()
                if not c:
                    return
                w_idx = ord(c[0]) - ord('A')
                if 0 <= w_idx < len(weapon_types):
                    success = m.ready_weapon(w_idx, self.asset_mgr)
                    if success:
                        self.text_log.add_message(f"Success! {m.name} readied {m.weapon.name}.")
                    else:
                        self.text_log.add_message("Cannot ready that weapon!")
                else:
                    self.text_log.add_message("Invalid weapon selection!")

            self.text_log.prompt("Ready Weapon? (A-P): ", callback=_on_weap, single_char=True)

        self.text_log.prompt("Ready Weapon: Which member? (1-4): ", callback=_on_member, single_char=True)

    def _prompt_wear_armor(self) -> None:
        """Equip armor on selected party member with A-H selection and inventory tracking."""
        def _on_member(m_str: str) -> None:
            try:
                idx = int(m_str.strip()) - 1
            except ValueError:
                self.text_log.add_message("Invalid member #!")
                return
            m = self.party.get_member(idx)
            if m is None:
                self.text_log.add_message("Invalid member #!")
                return

            armor_types = list(ArmorType)
            self.text_log.add_message(f"-- Wear Armor for {m.name} --")
            for a_idx, at in enumerate(armor_types):
                letter = chr(ord('A') + a_idx)
                if at == ArmorType.NONE:
                    self.text_log.add_message(f"{letter} - Skin")
                    continue
                cnt = m.armors.get(at, 0)
                is_equipped = (m.armor == at)
                if cnt > 0 or is_equipped:
                    status_tag = " (worn)" if is_equipped else f" ({cnt})"
                    self.text_log.add_message(f"{letter} - {at.name.capitalize()}{status_tag}")

            def _on_arm(a_code: str) -> None:
                c = a_code.strip().upper()
                if not c:
                    return
                a_idx = ord(c[0]) - ord('A')
                if 0 <= a_idx < len(armor_types):
                    success = m.wear_armor(a_idx, self.asset_mgr)
                    if success:
                        self.text_log.add_message(f"Success! {m.name} wears {m.armor.name}.")
                    else:
                        self.text_log.add_message("Cannot wear that armor!")
                else:
                    self.text_log.add_message("Invalid armor selection!")

            self.text_log.prompt("Wear Armor? (A-H): ", callback=_on_arm, single_char=True)

        self.text_log.prompt("Wear Armor: Which member? (1-4): ", callback=_on_member, single_char=True)

    def _prompt_yell(self) -> None:
        """Yell a word or phrase into town."""
        def _on_yell(phrase: str) -> None:
            p = phrase.strip().upper()
            if not p:
                return
            self.text_log.add_message(f"Thou yellest: '{p}'!")
            if p == "EVOCARE":
                if self.audio is not None:
                    self.audio.play_sfx("magic")
                self.text_log.add_message("The walls shimmer with ancient energy!")

        self.text_log.prompt("Yell what? ", callback=_on_yell)

    def update(self, dt: float) -> None:
        self.anim_timer += dt
        if self.anim_timer >= 0.2:
            self.anim_timer = 0.0
            self.anim_frame = (self.anim_frame + 1) % 4

    def render(self, surface: pygame.Surface) -> None:
        surface.fill(EGA_BLACK)
        w, h = surface.get_width(), surface.get_height()
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
