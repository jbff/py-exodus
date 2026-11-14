"""Dynamic castable spell mapping — port of Java ``Spell.getCastables``.

Java truth (gdx-exodus ``exodus/Constants.java:751-762``)::

    public static Map<String, Spell> getCastables(PartyMember pm, MapType mt) {
        Map<String, Spell> ret = new HashMap<>();
        Profession prof = pm.getPlayer().profession;
        int count = Keys.A;
        for (Spell s : Spell.values()) {
            if (s.canCast(prof) && s.canCastLocation(mt) && s.getCost() <= pm.getPlayer().mana) {
                ret.put(Keys.toString(count), s);
                count++;
            }
        }
        return ret;
    }

with the gates themselves at Constants.java:774-781 — ``canCast(prof)`` is
``(prof.val() & castableMask) > 0`` and ``canCastLocation(mt)`` is
``(mt.val() & locationMask) > 0``. The walk is in ``Spell.values()`` enum
order, letters run A.. sequentially over the survivors (so dropped entries
compact the alphabet), and the result is data for the letter-keyed menu.

Menu row format (Java truth, ``SpellInputProcessor.java:36-39``)::

    screen.log(String.format("%s - %s (%d)", key, spell, spell.getCost()));

``%s`` on the enum constant prints its NAME (e.g. ``PONTORI``), and the cost
is ALWAYS printed — 0 included — so a 0-cost spell renders ``A - PONTORI (0)``.

Callers: CombatScreen.java:324 builds the combat menu with
``MapType.combat``; SecondaryInputProcessor.java:283 passes the current map
type; SecondaryInputProcessor.java:443 passes ``MapType.dungeon``.

Seam (why ``discipline`` exists here and not in Java): Java builds ONE
interleaved letter map per caster — it has no discipline split. py's prompt
flows already resolve the cleric-vs-wizard discipline UPSTREAM —
``get_castable_spell_types`` (magic.py:184-208) for single-discipline
professions, and the "[W]izard or [C]leric" prompt for druid/ranger — and
hand the resolved discipline into ``_ask_spell_code`` at both call sites
(screens/combat_screen.py:245-304 and combat/magic.py
``prompt_cast_party._ask_spell_code``). ``get_castables(caster, context,
discipline)`` therefore takes the RESOLVED discipline (never a CHOOSE
sentinel: the CHOOSE case is decided before this walk runs, and a druid's
two menus are two calls). ``discipline=None`` reproduces Java's undivided
walk exactly (each py spell carries exactly one ``spell_type`` and each
discipline has 16 spells, so the combined walk can never exceed 26 letters).

Cheats (USER-DIRECTED GBC-RULES DEVIATION 2026-11-14, GBC cheat.c:414-825):

- ``no_class`` — the discipline MENU gate widens upstream
  (``get_castable_spell_types`` hands out both lists); inside this walk
  NOCLASS opens the per-spell profession gate, the same shape as the
  ``cast_spell`` gate at magic.py:290.
- ``full_mp`` — the ``cost <= mana`` filter is skipped entirely (the
  spell-selection-time hook mirrors ``debug.apply_full_mp``, which tops
  the caster up at prompt open; here the filter that Java keeps is
  relaxed, since the cheat guarantees mana is never the blocker).

``cheats_ok=False`` ignores ``debug.CHEATS`` entirely — the pure-Java
filter chain (used by parity-audit paths and tests).
"""

from __future__ import annotations

from typing import Any

from py_exodus import debug
from py_exodus.constants import MapType, Spell

#: context string -> Java MapType (Constants.java:248-257). "combat" maps to
#: MapType.combat; world/city/dungeon are their own MapTypes; "shrine" is
#: accepted because Java callers pass whatever ``bm.getType()`` holds.
_CONTEXT_MAPTYPES: dict[str, MapType] = {
    "combat": MapType.COMBAT,
    "world": MapType.WORLD,
    "city": MapType.CITY,
    "dungeon": MapType.DUNGEON,
    "shrine": MapType.SHRINE,
}

#: Defensive cap on letters (Java counts libgdx Keys A.. and would run past
#: Z; with 16 spells per discipline and one discipline per spell the walk
#: tops out at 16 entries for a split list — but never trust an enum size).
_MAX_LETTERS = 26


def get_castables(
    caster: Any,
    context: str,
    discipline: str | None = None,
    *,
    cheats_ok: bool = True,
) -> list[tuple[str, Spell]]:
    """Walk the Spell enum in declaration order, Java getCastables style.

    Returns ``[(letter, Spell), ...]`` with letters ``"A","B",...`` assigned
    sequentially over the surviving spells. Filters, per
    Constants.java:751-762:

    - ``discipline`` (py-only): keep spells whose ``spell_type`` matches the
      RESOLVED discipline the caller's prompt flow selected (``None`` = the
      Java-faithful undivided walk);
    - ``canCast(prof)`` — ``profession.mask & spell.castable_mask``
      (Constants.java:774-777), bypassed when ``debug.CHEATS.no_class`` is
      on and ``cheats_ok``;
    - ``canCastLocation(mt)`` — ``mt.mask & spell.location_mask``
      (Constants.java:779-781), where ``mt`` comes from ``context``;
    - ``cost <= mana`` — ``spell.cost <= char.mp`` (Constants.java:757),
      skipped when ``debug.CHEATS.full_mp`` is on and ``cheats_ok``.
    """
    key = str(context).strip().lower()
    try:
        map_type = _CONTEXT_MAPTYPES[key]
    except KeyError:
        raise ValueError(f"unknown spell-menu context: {context!r}") from None

    no_class = cheats_ok and debug.CHEATS.no_class
    full_mp = cheats_ok and debug.CHEATS.full_mp

    char = getattr(caster, "character", caster)
    prof = getattr(char, "profession", None)
    mana = getattr(char, "mp", 0)

    if discipline is not None:
        discipline = str(discipline).strip().lower()

    castables: list[tuple[str, Spell]] = []
    for spell in Spell:
        if discipline is not None and spell.spell_type != discipline:
            continue
        if not no_class and (prof is None or not spell.can_cast(prof)):
            continue
        if not (map_type.mask & spell.location_mask):
            continue
        if not full_mp and spell.cost > mana:
            continue
        if len(castables) >= _MAX_LETTERS:
            break  # pragma: no cover — unreachable with the 32-spell enum
        castables.append((chr(ord("A") + len(castables)), spell))
    return castables


def spell_menu_prompt_lines(castables: list[tuple[str, Spell]]) -> list[str]:
    """Render the menu rows exactly as Java does (SpellInputProcessor.java:36-39):
    ``"{letter} - {SPELL_NAME} ({cost})"``, cost always printed, 0 included."""
    return [f"{letter} - {spell.name} ({spell.cost})" for letter, spell in castables]
