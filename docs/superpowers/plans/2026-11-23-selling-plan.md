# Plan: selling weapons and armour, and autoplay selling excess gear

Status: plan only, not implemented (user, 2026-11-23: "DO NOT IMPLEMENT ... i
will tell you when to implement").

## What LairWare does (refs/ultima3, Sources/UltimaMisc.c, shop cases 3 and 4)

- Weapon shop (case 3) and armour shop (case 4) both ask "Buy or Sell?"
  (messages 207 / 211). Anything but B goes to the sell branch.
- **Price = the buy price.** Sell reads the same `WeaponsArmour.plist` index
  as buy: weapons `input + 25`, armour `input + 41`, where the table is
  0-based (`CFArrayGetValueAtIndex`). So a Bow sells for 350 and Plate for
  2500. There is no half-price rule.
- **Only what that shop stocks.** The letter must be below `opnum`, the same
  bound as buying. Ordinary shops take weapons B..H (Dagger..2-H-Sword) and
  armour B..E (Cloth..Plate). Dawn (`Party[4] == 37`) takes weapons B..O
  (to +4 Sword) and armour B..G (to +2 Plate). Hands (A) get an alert and
  Skin is out of range, so Exotics can never be sold.
- **"You don't own one of those!"** (212) ends the visit when the count is 0.
- **Gold cap.** `AddGold(rosNum, amount, FALSE)`: if the seller's purse would
  pass 9999, the sale is cancelled ("More gold than thou can carry! Sale
  cancelled.", 214) and the item kept.
- **Selling the readied item.** Counts include the readied piece. If the
  count reaches 0 and it was readied, the member reverts to hands / skin
  (`Player[48] = 0` / `Player[40] = 0`).
- After a sale it loops back to "for sale?" ("Thank you!", 213).

## What our port does now (py_exodus/screens/vendor_dialog.py, BuySellVendorDialog)

Selling already exists, ported from Java WeaponVendor/ArmorVendor. It differs
from LairWare on rules:

| Rule | Ours (Java) | LairWare |
|---|---|---|
| Sell price | `price // 2` | full `price` |
| What can be sold | full vendor-class catalog (b..o) at any shop | that shop's own stock (vendor.items) |
| 9999 purse cap | none (direct gold write) | sale cancelled if it would overflow |
| Readied piece | can't be sold (our model keeps it out of `weapons`/`armors`) | can be sold; member reverts to hands/skin |

Prices in `assets/xml/vendor.xml` already match LairWare's table. Per-town
stock already matches the LairWare ranges: 7/4 ordinary, 14/6 Dawn.

## Part 1: LairWare selling rules (commit 1)

Keep the Java conversation UI and its strings. Port only the rules:

1. **Full price.** `SELL_ITEM` credits `price * count`, and the
   `WAIT_SELL_INPUT` / `WAIT_SELL_HOW_MANY` / `WAIT_SELL_ONE` texts show
   `price`, not `price // 2`.
2. **This shop's stock only.** `_sell_catalog()` returns `self.vendor.items`.
   `_catalog_item_for_choice()` uses `self.vendor.get_item()`, so a
   non-Dawn shop refuses +2/+4 pieces.
3. **Purse cap.** In `SELL_ITEM`, if `player.gold + price * count > 9999`,
   don't sell. Say "More gold than thou can carry! Sale cancelled." and go
   back to ASK_BUY_SELL. A many-unit sale gets the same all-or-nothing check
   (LW sells one at a time).
4. **Readied piece.** Count the readied piece as owned in `_owned()` (bucket
   count + 1 if readied). When a sale would take the last one, unequip
   first: weapon → `WeaponType.NONE`, armour → `ArmorType.NONE`. *Decision
   for the user:* port this (parity) or keep "can't sell what you're
   wearing" (safer for manual play). Recommendation: port it; it's the rule.

Tests (tests/test_vendor_dialog*.py or a new tests/test_selling.py). Drive the
dialog with set_response/next_dialog:
- A Bow sells for 350 (was 175).
- A non-Dawn weapon shop refuses a +2 Axe ("don't have"/no such); Dawn
  accepts it.
- A seller at 9800 gold selling Plate (2500) is cancelled, item kept.
- Selling the only (readied) Sword leaves the member on hands, gold +200.
- Selling 3 of 3 daggers credits 15.

README: the shops line under rules ported from LairWare gets "sell at full
price, only what that shop stocks, never past 9999 gold".

## Part 2: autoplay sells excess gear (commits 2 and 3)

### Rule (user, 2026-11-23)

Sell only when the party is **already in a town with weapon/armour shops**
for its own reasons. The overworld never decides to travel somewhere to
sell; no new goal, no new trip. Selling inside a town risks nothing.

### 2a. `excess_gear(party, weapon_stock, armour_stock)` (autoplay/equipment.py, pure)

Returns `[(member_idx, kind, type, count)]` to sell at this shop. A piece
the member owns is excess unless one of these keeps it:

- It is the member's readied weapon / worn armour (we never sell those, so
  the readied/count rule above doesn't matter here).
- It is the member's best usable weapon in **either** mode,
  `best_owned_weapon(m, True)` or `(m, False)`. The ranged/melee preference
  flips after exotics (`prefer_ranged_weapons`), so keep both.
- It is something `best_hand_transfer` would give another member: better
  than that member's current piece in either mode, and usable by their
  class (`can_use_armor`, weapon class limits). Equivalently, keep the
  party's best usable piece for every living member that doesn't already
  wear one at least as good.
- It is a Wizard's dagger (the `include_wizard_dagger` rule).
- It belongs to a dead member. Their gear waits for the resurrection, so
  don't touch it.
- It is not in this shop's stock (can't be sold here). Exotics are never in
  stock.

Duplicates beyond the one kept are excess. Each test should state what the
upgrade logic would do: never sell anything `best_shop_upgrade` (or the
hand-off) would want back. Otherwise buy/sell/buy loops become possible.

Tests: a fighter with Exotic readied and a spare Sword + Bow sells both
(non-Dawn). A spare Bow is kept when the Wizard... (n/a, wizards: dagger
only). A Sword is kept when the Thief carries only a Dagger (hand-off
candidate). A +2 Axe is not listed at Grey but is at Dawn. A dead member's
spares are kept. Excess is empty for a fresh party.

### 2b. The sell errand in town (autoplay/controller.py, `_step_town`)

- **When (user, 2026-11-23): just before LEAVING the town, not on entering.**
  Buying during the visit (an upgrade, a hand-off) is what creates spare
  gear, so the check runs once the town's errands are done and the party
  is about to walk out. Hook it at the point where `_step_town` would head
  for the exit (the goal no longer wants anything here). If
  `excess_gear(...)` is non-empty for this town's stock, sell first, then
  leave.
- Where: after `_maybe_manage_gear`, so hand-offs and readies settle before
  anything counts as excess. Towns: `_SHOP_TOWNS` (Britain, Grey, Montor E/W,
  Dawn), using the same `wep_stand_xy` / `arm_stand_xy` stands the buyer
  uses (with the merchant-present fix above).
- Skip in an emergency: a poisoned member at ≤25 HP, or anyone at 0 food.
  Leave at once; selling waits for the next visit.
- Purse cap: sell from the owner, and skip a piece that would push the
  owner past 9999 (the shop would cancel it). A later "join gold" doesn't
  need to be planned.
- Flow (reuse the buy path): walk to the stand → `T`, member, direction →
  "Buy or Sell?" → **S** → "Which wouldst you sell?" → letter → (count>1)
  "How many?" → count → "Anything else?" → **N**. One piece per talk, like
  the guild buys; the loop comes back while excess remains.
  - New state: `self._sell_plan = (member_idx, letter, count)`. The prompt
    handler answers "buy/sell" with `s` when `_sell_plan` is set, else `b`
    (today it is always `b`). It answers the sell letter and the count, and
    clears `_sell_plan` on "Anything else?".
- Stand to use: weapon stand for weapons, armour stand for armour. Do all
  weapons first, then armour, to save walking.
- No goal changes in planner.py. Selling is an in-town side task, like gear
  management.

Tests (tests/test_autoplay_trip.py style):
- In Grey with a spare Bow owned by member 2: the controller walks to the
  weapon stand and the prompt sequence answers S, the Bow's letter, N. Gold
  +350 and the Bow is gone (drive with real TownScreen + dialog).
- On the overworld with excess gear and goal GRIND: no trip to a shop town
  (the goal/trip is unchanged).
- Buys an upgrade in Grey, then with the old piece now spare, sells it
  before walking out (check runs at exit, not entry).
- A member at food 0 or poisoned near death: walks out without selling.
- A piece the hand-off wants is not sold; a dead member's spares are not
  sold.
- Purse at 9800: the Plate is not offered.

### Optional, flagged: Death Gulch

Death Gulch has a weapon shop (Gulch Weaponry) and an armour shop
(Ragnarrson Armour). Late-game parties raid there repeatedly holding
leftover pre-exotic gear, so it's the best selling spot. But it isn't in
`_SHOP_TOWNS`, and its layout (counters, guards, raid pathing) differs.
Leave it for a follow-up once the five ordinary towns work, and ask the
user first.

## Prerequisite fix (queued by the user, 2026-11-23): talk only to a merchant who is there

Montor East's Ace Armour (Sven at (35,10), Ivar at (37,10)) and Acme
Weaponry (Caladan, Brood) each have two merchants who don't follow the
party along the counter. Autoplay stands at the fixed stand and Transacts
north across the counter, talking to nobody. Generic fix, for buying and
selling alike:

- Before pressing T at a shop stand, check that a merchant NPC (the shop's
  vendor) is across the counter in the talk direction.
- If not, walk along the counter row to the nearest stand facing a merchant,
  then T. Usually the first check passes (the vendor follows the party); at
  Montor East it finds the stationary one.
- Test: Montor East armour shop with the party at (35,12) and no merchant
  across: it moves to the stand opposite Sven or Ivar before T. Ordinary
  shop with the vendor across: T at once.

Do this before Part 2: the sell errand uses the same stands.

## Order and verification

1. Commit 1: LairWare sell rules + tests + README. Full suite RC 0.
2. Commit 2: `excess_gear` + tests.
3. Commit 3: controller sell errand + prompt answers + tests + README
   autoplay line ("sells spare weapons and armour when already in a shop
   town").
4. One batch of 10 fresh seeds. Metric: gold from sales per run and no
   buy/sell loops (count shop talks per town visit). Compare the win rate
   loosely against the 5b48f81 batches.

## Open questions for the user

1. Selling the readied piece in manual play: port LairWare (reverts to
   hands/skin) or keep it unsellable? Recommendation: port it.
2. Death Gulch selling: later, after the ordinary towns? Recommendation:
   yes, later.
