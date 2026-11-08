"""Portal entry shared by every exploration screen (Java
``exodus/GameScreen.java:538-556``): E is available on every map including
towns. The Ambrosia→Sosaria whirlpool portal has two distinct Java routes:

- step-in (``preMove``, GameScreen.java:661-670) — the party is ferried to a
  random Sosaria coast tile (Utils.getRandomBetween(48, 53) / (0, 8));
- pressing E at the portal (GameScreen.java:538-556) — the party arrives at
  the portal's fixed ``startx``/``starty`` (maps.xml: ``startx="1"
  starty="1"``) — no randomizing.
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from py_exodus.world.map import GameMap


def set_coords(screen, x: int, y: int) -> None:
    """Write the party position onto whichever coordinate the screen models."""
    if hasattr(screen, "avatar_x"):
        screen.avatar_x, screen.avatar_y = x, y
    else:
        screen.party.x, screen.party.y = x, y


def step_in_whirlpool_portal(screen, x: int, y: int) -> bool:
    """Java GameScreen.java:661-670 — on Ambrosia, stepping onto the
    WHIRLPOOL portal tile ferries the party to a random Sosaria coast.
    Returns True when the intercept happened (the move is complete)."""
    if not hasattr(screen, "_load_world_map"):
        return False
    map_id = getattr(screen, "map_id", None)
    game_map = getattr(screen, "game_map", None)
    if game_map is None or map_id != 13:
        return False

    portal = game_map.get_portal(x, y)
    if portal is None or str(getattr(portal, "name", "") or "").upper() != "WHIRLPOOL":
        return False

    dx = random.randint(48, 53)
    dy = random.randint(0, 8)
    if screen.audio is not None:
        screen.audio.play_sfx("wave") or screen.audio.play_sfx("whirlpool")
    screen.map_id = 0
    screen._load_world_map()
    screen.party.x, screen.party.y = dx, dy
    return True


def enter_portal(screen, x: int, y: int) -> bool:
    """Handle E at (x, y) on any map (Java GameScreen.java:538-556).

    Returns True when a portal is present (handled or gated), False when
    nothing is here. Destination dispatch is Java's loadNextMap: shrines
    (55-58), dungeons (14-20), otherwise a town; same-map destinations
    reposition the party at the portal start.
    """
    game_map = getattr(screen, "game_map", None)
    if game_map is None:
        return False

    portal = game_map.get_portal(x, y)
    if portal is None:
        return False

    dest_id = portal.dest_map_id
    start_x = portal.start_x
    start_y = portal.start_y
    is_overworld = hasattr(screen, "_load_world_map")

    # Dawn is reachable only during a double new moon (GameScreen.java:544-547).
    if dest_id == 11 and hasattr(screen, "trammel_phase"):
        if screen.trammel_phase != 0 or screen.felucca_phase != 0:
            screen.text_log.add_message(
                "The mythical city of Dawn only appears during a double new moon!"
            )
            return True

    if dest_id == getattr(screen, "map_id", None):
        # Same-map destination: just reposition (GameScreen.java:550-553).
        set_coords(screen, start_x, start_y)
        return True

    if is_overworld and dest_id == 0:
        # World-map relocation: the Ambrosia whirlpool return portal arrives
        # at the portal's fixed start (maps.xml startx="1" starty="1").
        screen.map_id = dest_id
        screen._load_world_map()
        screen.party.x, screen.party.y = start_x, start_y
        return True

    if dest_id in (55, 56, 57, 58):  # Shrine
        from py_exodus.screens.shrine import ShrineScreen

        stat_names = {55: "wisdom", 56: "dexterity", 57: "intelligence", 58: "strength"}
        shrine = ShrineScreen(
            party=screen.party,
            stat_name=stat_names.get(dest_id, "strength"),
            asset_mgr=screen.asset_mgr,
            return_screen=screen,
            manager=screen.manager,
        )
        _push(screen, shrine)
        return True

    if dest_id in (14, 15, 16, 17, 18, 19, 20):  # Dungeons
        from py_exodus.screens.dungeon_screen import DungeonScreen

        dungeon = DungeonScreen(
            party=screen.party,
            map_id=dest_id,
            asset_mgr=screen.asset_mgr,
            audio=screen.audio,
            return_screen=screen,
            manager=screen.manager,
        )
        _push(screen, dungeon)
        return True

    if dest_id == 0 and not is_overworld:
        # A town walking through a dest-0 portal exits to the world map
        # at the portal start (GameScreen.java:548-549 loadNextMap).
        screen.party.x, screen.party.y = start_x, start_y
        screen.exit_screen()
        return True

    from py_exodus.screens.town import TownScreen

    town = TownScreen(
        party=screen.party,
        map_id=dest_id,
        start_x=start_x,
        start_y=start_y,
        asset_mgr=screen.asset_mgr,
        audio=screen.audio,
        return_screen=screen,
        manager=screen.manager,
    )
    _push(screen, town)
    return True


def _push(screen, next_screen) -> None:
    if screen.manager is not None:
        screen.manager.push_screen(next_screen)
    else:
        screen.next_screen = next_screen
        screen.is_finished = True
