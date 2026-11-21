# Autoplay transport layer, pirate firing lanes, original spawn rate (2026-11-21)

Three changes, measured together on 100 seeds at the user's request (spawn rate, then
pirate lane, then transport, with one batch at the end).

## 1. Original-game spawn rate, placement, cap, persistence (`05caeae`)

User ruling: spawning follows the original game. LairWare `SpawnMonster` / `FinishAll`
(`refs/ultima3/Sources/UltimaMisc.c:1111-1186`), now in `screens/overworld.py`:

| | Java (before) | Original (now) |
|---|---|---|
| chance per turn | 25% + forced spawn when none exist | 7/135 (5.2%) |
| placement | 8-12 tiles from the party | random tile anywhere, never the party's row or column |
| cap | 6 on screen / 8 total | 32 slots (whirlpools not counted) |
| despawn | beyond 24 tiles | never (monsters persist and home in) |
| new map | 3 spawns near the party | 500 rate-gated calls (~26 monsters) |

## 2. Pirate firing lane rule (`autoplay/threats.py`)

Engine: a pirate fires every tick while the party is in its row or column at movement
distance 2-3 and its broadside faces the party; a misaligned pirate turns 1-in-2 and fires
next tick. Distance 1 is the battle (that is how a ship is captured).

Rule, checked first on every overworld tick (`AutoPlayController._threat_escape`, before any
spell or move): never end a turn in a lane.

- On foot: attack an orthogonally adjacent pirate; else step next to the lane pirate (fight
  next turn) when the party is not under 40% HP; else step to the safe tile farthest from it.
- On a ship (moves only along its heading; any other direction spends the turn turning; the
  wind blocks one direction): sail on to a safe tile (closing to distance 1 counts as safe);
  else fire the broadside if it bears on the lane pirate; else turn toward a way out.
- Lane tiles are hard-avoided in path planning, and `_lane_guard` (inside `_emit_key`) turns
  any move into a lane into a wait on the current (safe) tile.
- Cannons no longer target pirates outside the lane logic (distance 2-3 means escape,
  distance 1 means fight).

Squids (user policy) until a living Cleric/Druid can hold ALCORT (max MP >= 35): never end a
turn within distance 1 (engagement), stay 3+ tiles off them on foot (avoid set), cannon them
from a ship.

## 3. Transport layer (`autoplay/trip.py`, follower in `controller.py`)

Goal handlers name a `Destination(tiles, need FOOT/SHIP/None, label)` plus an arrival action
(E, DIG, search, yell). `plan_trip` runs Dijkstra over `(x, y, FOOT|SHIP)`:

- walk (1/tile), sail (1.5/tile, x4 with a critical hull), board B at a frigate (+300 for a
  wrecked last ship), leave X at water next to walkable land, moongate hop (50; phases
  p = 0..23, trammel = p // 3, felucca = p % 8), capture (250: wait on a coast tile for a
  pirate, fight it, board its frigate);
- a reverse transition at the same tile within 50 turns costs +200 (no B/X ping-pong);
- tiles under threat when planning (lanes, squid reach) cost +60, squid coast +5.

The follower (`_trip_drive`) executes legs and is the only code that emits B or X (a test
parses the controller to enforce this). It re-plans when the destination, map, transport mode
or frigate set changes, when the party is more than 3 tiles off the planned path, every 300
turns, or after 30 turns without moving (gate and capture waits excepted). A capture wait with
no pirate within 12 tiles for 600 turns bans that stretch of coast and re-plans.

The planner (`autoplay/planner.py`) no longer looks at the transport mode: CAPTURE_SHIP is
gone (DIG_EXOTICS / SAIL_WHIRLPOOL name the destination, the trip decides that a ship is
needed), and food, healing, shopping, keys, gems and torches are no longer suppressed at sea.
`at_exotic_island` is position-only. So boarding or landing can never flip the goal.

Deleted: the 17 old B/X sites, `_enter_portal_or_wait_dawn`, `_step_ambrosia`,
`_hunt_starving_prey_or_patrol`, `_pick_moongate_dest`, `_step_moongate`, `_safe_shore_water`,
`_get_any_shore_water`, `_boardable_frigates`, `_nearest_reachable_portal`,
`_nearest_shop_town_portal`, and the on-ship pirate standoff.

## Reproducibility

`batch.run_seed` now also seeds `tile_effects._rng` and derives each dungeon's
`random.Random()` from the global stream. With `PYTHONHASHSEED=0` a seed replays exactly.
