# Presentation pass + monster variants: design

Date: 2026-11-22. Agreed in conversation with the user; built in this order, one
commit and push to `master` per item, full test suite (exit code 0) before each push.

## Intent

Make py-exodus look and read like a finished game, borrowing LairWare's
presentation where it is better than the Java port's (LairWare is the
authority), and restore one piece of original flavour the Java port lost:
monster variant names. No gameplay rule changes except where LairWare says so.

## Goals / non-goals / anti-goals

- Goals: the seven items below, each shippable on its own.
- Non-goals: dungeon wireframe changes, new music, mouse input, NES/GBC art.
- Anti-goals: anything that breaks existing saves, slows autoplay batches,
  or makes `--tiles` a large refactor (user: "if it is at all not
  straightforward I do not want to do it").

## Constraints

- No binary *data* files at runtime (memory rule): LairWare's resource-fork
  data (the View script, the signature strokes) is extracted once into JSON.
  Images (PNG/GIF) are fine, like the current tile atlas.
- LairWare code is MIT; its art ships in its repo. Credit it on the menu.
- Headless batches (`SDL_VIDEODRIVER=dummy`) must keep working; the intro
  and the View never run in batch/autoplay-from-CLI startup paths.

## Approaches considered

For `--tiles`: (a) slice a LairWare sheet into the existing
`AssetManager.get_tile_surface(name, frame)` lookup, falling back to the
current atlas for any tile a sheet lacks; (b) rewrite the renderer around
LairWare's sheet grid. Picked (a): our 64 tile indexes equal LairWare's, so
it is a loader change. (b) is the refactor the user ruled out.

For the intro: (a) reproduce LairWare's sequence from its own images and
extracted data; (b) redraw our own art. Picked (a): the user wants the
LairWare/C64-style intro itself.

## The seven items (user-approved order)

1. **Monster variant names.** LairWare `SpawnMonster` (UltimaMisc.c:1181-1185):
   no variant half the time, else variant 1 or 2. `PrintMonster`
   (UltimaText.c:642-646) names Thief..Balron variants from Tiles.plist
   64-79: Thief→Brigand/Cutpurse, Orc→Goblin/Troll, Skeleton→Ghoul/Zombie,
   Giant→Golem/Titan, Daemon→Gargoyle/Mane, Pincher→Snatch/Bradle,
   Dragon→Griffon/Wyvern, Balron→Orcus/Devil (plurals from
   TilesPlural.plist). Stats unchanged. The variant rides the overworld
   creature into combat for messages; the tile art uses it when the active
   sheet has variant cells. Fix the old "Pincher (Orcus)" / "Dragon (Wyvern)"
   comments in the spawn table.
2. **`--tiles NAME`.** Copies of LairWare's 12 `*-Tiles` sheets under
   `assets/graphics/lairware/`. Grid: 12×16 cells, tile *n* at column pair
   *n*//16, row *n*%16, frame 0 left, frame 1 right. Loaded into the same
   name→frames table, scaled (nearest) to our tile size; tiles a sheet lacks
   keep the current art. `--tiles list` prints the names. Default unchanged.
3. **Font.** Bundle Barlow Semi Condensed (OFL, license file alongside);
   replace gnuolane in the HUD, log and menus; render at whole-pixel sizes
   chosen per area; the message log gets a larger size.
4. **Roster screen** (Organize Party) in LairWare's layout: one row per
   character (name, level, status + race + class + sex in words), party
   members in bold yellow, Poisoned green / Dead red / Ashes gray, banded
   columns, all 20 slots shown. Fixes today's truncation, hidden 6th entry
   and clipped help keys.
5. **Right-hand party panel**: the approved mockup
   (`.superpowers/brainstorm/.../panel-full.html`): framed member rows
   (no `[n]` numbers) with race/class/sex/level in words, HP/MP bars,
   food, gold, stats, readied weapon and worn armor, status-colored edge and
   POISONED/DEAD tag; then Party supplies, Quest chips (marks, cards,
   exotics), and location/turn/autoplay (with goal)/autocombat. Nothing
   shown today is lost.
6. **Main menu**: Exodus art at the top; "From the depths of hell" /
   "he comes for vengeance!" on two lines; the existing options; credits at
   the bottom: *Ultima III: Exodus* (Richard Garriott / Origin Systems, 1983),
   the Java port gdx-exodus (Paul Antinori), the LairWare port (Leon McNeill).
   A "Return to the View" option once item 7 lands.
7. **Intro + the View.** LairWare `Intro()`: Exodus logo fades in over the
   stalactite border, "by Lord British" signature drawn stroke by stroke,
   the five-frame duel animation, "press any key"; then `Demo()`: the View,
   a scripted Sosaria scene (512-step script) cycling songs until a key.
   Data: `DEMO` and `SGNT` resources extracted once from
   `MainResources.rsrc` to JSON by a script kept in `scripts/`. Any key
   skips; skipped entirely in headless/autoplay batch runs.

## Left to the builder

Exact pixel sizes, colors within the approved mockups, module layout,
and test shapes (each item gets tests; behaviour items get a test that fails
on the old code).
