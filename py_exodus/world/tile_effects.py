"""Tile-rule effects, tile speeds, and the shared applyEffect port.

Java truth:
- ``exodus/Party.java:279-283`` — ``Party.applyEffect`` fans out
  unconditionally: every non-DEAD member takes the effect as-is.
- ``exodus/Party.java:342-368`` — ``PartyMember.applyEffect``: GREMLINS
  drains 2 food (floored at 0); LAVA/FIRE deal ``16 + rand(32)`` damage
  through the ``apply_damage`` chokepoint (Task 2 death flow) unless the
  member carries the Mark of Fire (``marks[1]``); POISON/POISONFIELD set
  POISONED (no damage); ELECTRICITY is a no-op.
  USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): the LAVA/FIRE damage in
  ``apply_effect_to_member`` below is flat 50 (GBC funcs5.c:1287-1310; LW
  corroborates flat 50); the Mark-of-Fire immunity is unchanged.
- ``exodus/Party.java:285-306`` — the per-member-rolled overload
  ``Party.applyEffect(PartyMember, effect)`` (LAVA/FIRE/GREMLINS 1-in-2,
  POISON/POISONFIELD 1-in-5) belongs to exploration's cousin: Java's only
  caller is ``CombatScreen.java:372``. Kept here for Task 12's combat work;
  nothing on the 2D exploration maps calls it.
- ``exodus/GameScreen.java:706-754`` — every turn on the 2D maps (a move, a
  blocked move, a pass) runs ``finishTurn``: the endTurn tick, then the
  tile-rule effect of the tile the party occupies at the start of the turn.
- ``exodus/Context.java:212-240`` — ``slowedByTile``: one chance in 8 (SLOW),
  4 (VSLOW) or 2 (VVSLOW) that a combat creature's move is lost. Java's only
  caller is ``CombatScreen.java:937`` — exploration movement is never
  slowed; kept here for combat (Task 12+), with no exploration call sites.
- ``objects/BaseMap.java:719-744`` — on foot the avatar may only enter a
  ``dispelable`` (field) tile when some member carries the Mark of Force
  (``marks[3]``).
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

from py_exodus.constants import Status, TileEffect, TileSpeed

if TYPE_CHECKING:
    from py_exodus.assets import TileDef
    from py_exodus.entities.party import Party

#: Default die used when a caller passes no explicit ``random.Random``.
#: Tests may replace this attribute to make rolls deterministic.
_rng = random.Random()


def _rolled(n: int, rng: random.Random | None) -> bool:
    """Java ``rand.nextInt(n) == 0``: True one time in n."""
    source = rng if rng is not None else _rng
    return source.randrange(n) == 0


# --- Tile speeds (Context.java:212-240 slowedByTile) ---
#
# Combat-only in Java (CombatScreen.java:937 is the sole caller); retained
# here for Task 12's combat work. Exploration movement must not roll it.


def slowed_by_tile(tile: TileDef, rng: random.Random | None = None) -> bool:
    """Default movement-slowing handler: True when the move's turn is lost.

    Java ``Context.slowedByTile``: a SLOW tile rolls 1-in-8, VSLOW 1-in-4,
    VVSLOW 1-in-2; FAST (and no matching speed) never slows. A lost roll
    leaves the creature without displacement for the turn.
    """
    speed = getattr(tile, "speed", TileSpeed.FAST)
    if speed is None:
        return False
    if speed == TileSpeed.SLOW:
        return _rolled(8, rng)
    if speed == TileSpeed.VSLOW:
        return _rolled(4, rng)
    if speed == TileSpeed.VVSLOW:
        return _rolled(2, rng)
    return False


# --- Mark of Force passage (BaseMap.java:719-744; GBC postexo1.c:1861-1880) ---


def party_has_mark_of_force(party: Party | None) -> bool:
    """True when any living-or-dead party member carries ``marks[3]``.

    Java ``BaseMap.partyHasMarkOfForce`` checks ``marks[3] == 1`` on every
    member regardless of status.
    """
    if party is None:
        return False
    return any(m.marks[3] == 1 for m in party.members)


def all_members_mark_of_force(party: Party | None) -> bool:
    """GBC force-field passage: every living member carries ``marks[3]``.

    GBC ``postexo1.c:1861-1880`` starts ``forceOK`` set and zeroes it once
    for each unmarked member before returning it as the passage decision;
    the per-member strike only reaches ``status < 2``, so DEAD members
    neither take the 99 nor block the (vacuously) all-marked party.
    """
    if party is None:
        return False
    living = [m for m in party.members if not m.is_dead()]
    return all(m.marks[3] == 1 for m in living)


def force_field_blockers(party: Party | None, tile) -> list:
    """Living members a refused GBC force-field entry would strike, else [].

    Non-empty exactly when ``tile`` is the ENERGY (force) field and the
    all-marked passage fails (``all_members_mark_of_force`` above) — the
    same condition the walkability gate refuses on (renderer ``can_move_to``
    foot branch).
    """
    if party is None or tile is None:
        return []
    if getattr(tile, "rule", "") != "energy":
        return []
    if all_members_mark_of_force(party):
        return []
    return [
        m for m in list(party.members) if not m.is_dead() and m.marks[3] != 1
    ]


def apply_force_field_strike(party: Party | None, tile, message_logger=None) -> bool:
    """Refuse a GBC force-field entry and strike the unmarked, then True.

    USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): force field 99 damage to
    members lacking the Mark of Force; passage only when all marked
    (GBC postexo1.c:1861-1880). The movement validator fires in ANY context
    — overworld, town, wherever a step into tile 0x26 is refused — so every
    blocked-branch caller funnels here: the FORCE FIELD message goes to
    ``message_logger`` (when given) and each living member lacking
    ``marks[3]`` takes 99 through ``apply_damage`` (a DEAD member neither
    blocks nor takes the strike). ``PartyDeathException`` from a wipe
    PROPAGATES — the caller catches it and routes its own death check
    (``check_party_death``).
    """
    unmarked = force_field_blockers(party, tile)
    if not unmarked:
        return False
    if message_logger is not None:
        message_logger("FORCE FIELD!")
    for member in unmarked:
        member.apply_damage(99, False)
    return True


# --- Shared applyEffect port (Party.java:279-283, 342-368) ---


def apply_effect_to_member(
    member, effect: TileEffect, rng: random.Random | None = None
) -> None:
    """Apply a tile effect to one member (Party.java:342-368).

    Damage/food deltas route through ``PartyMember.apply_damage`` so the
    Task 2 death-flow chokepoint raises ``PartyDeathException`` on a wipe.
    A DEAD member is skipped, as in Java.
    """
    if member.is_dead():
        return

    if effect == TileEffect.GREMLINS:
        # Java: Utils.adjustValue(food, -2, 999900, 0) — floored at 0.
        member.food = max(0, member.food - 2)
    elif effect in (TileEffect.LAVA, TileEffect.FIRE):
        if member.marks[1] == 0:  # Mark of Fire absorbs the burn
            # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): flat 50
            # (GBC funcs5.c:1287-1310; LW corroborates flat 50), superseding
            # Java's 16 + rand(32) roll.
            member.apply_damage(50, False)
    elif effect in (TileEffect.POISON, TileEffect.POISONFIELD):
        if member.status != Status.POISONED:
            member.status = Status.POISONED
    # NONE and ELECTRICITY fall through with no effect (Java).


def apply_effect(
    party: Party | None, effect: TileEffect, rng: random.Random | None = None
) -> list:
    """Apply a tile effect to the party unconditionally (Party.java:279-283).

    Java truth: ``Party.applyEffect(effect)`` fans out to every non-DEAD
    member with no party-level die — ``CombatScreen.java:937``-style rolls
    live in the ``apply_effect_rolled`` overload below, used only by combat.
    Member behaviour is ported from ``PartyMember.applyEffect``
    (Party.java:342-368); damage routes through ``apply_damage`` so the Task
    2 death chokepoint raises ``PartyDeathException`` on a wipe.
    """
    if party is None:
        return []
    if effect == TileEffect.NONE:
        return []

    applied: list = []
    for member in list(party.members):
        apply_effect_to_member(member, effect, rng)
        applied.append(member)
    return applied


def apply_effect_rolled(
    party: Party | None, effect: TileEffect, rng: random.Random | None = None
) -> list:
    """Java ``Party.applyEffect(PartyMember, effect)`` (Party.java:285-306).

    The die-rolled party dispatch — LAVA/FIRE/GREMLINS 1-in-2,
    POISON/POISONFIELD 1-in-5, ELECTRICITY unconditional — rolled per member
    inside the loop, exactly as in Java. Java's only caller is
    ``CombatScreen.java:372``; nothing on the 2D exploration maps uses it,
    but Task 12's combat port will. Returns the members the effect was
    applied to; raises ``PartyDeathException`` when damage wipes the party.
    """
    if party is None or effect == TileEffect.NONE:
        return []

    applied: list = []
    for member in list(party.members):
        if effect in (TileEffect.LAVA, TileEffect.FIRE, TileEffect.GREMLINS):
            if not _rolled(2, rng):
                continue
        elif effect in (TileEffect.POISON, TileEffect.POISONFIELD):
            if not _rolled(5, rng):
                continue
        # ELECTRICITY is always dispatched (and is a member-level no-op).
        apply_effect_to_member(member, effect, rng)
        applied.append(member)
    return applied


def apply_rule_effect(
    party: Party | None, tile: TileDef, rng: random.Random | None = None
) -> list:
    """Apply the tile-rule effect of the tile the party is standing on.

    Java ``GameScreen.finishTurn`` (GameScreen.java:716-722): every turn
    applies ``getTile(currentX, currentY).getRule().getEffect()`` — the
    effect of the tile occupied at the start of the turn — through the
    unconditional ``Party.applyEffect`` fan-out.
    """
    effect = getattr(tile, "effect", TileEffect.NONE)
    if effect == TileEffect.NONE:
        return []
    return apply_effect(party, effect, rng)
