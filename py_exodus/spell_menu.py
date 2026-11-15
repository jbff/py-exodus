"""Fixed-letter spell cast menu.

USER-DIRECTED RULING (2026-11-15): fixed spell letters (B=APPAR_UNEM always);
availability refused at attempt — supersedes the Java getCastables letter
compaction (Constants.java:751-762) adopted 2026-11-14.

Each discipline carries the ORIGINAL GAME's alphabetical A-P letters as the
Spell enum's fixed ``code`` (cleric B=APPAR_UNEM ALWAYS; every discipline
holds 16 spells, so the menu is exactly A-P). The cast menu lists the
discipline's FULL fixed set — name + fixed letter + MP cost — and the
letters NEVER move with the caster's mana or the map context. This replaces
the 2026-11-14 port of Java ``Spell.getCastables`` (Constants.java:751-762),
which filtered ``canCast(prof) && canCastLocation(mt) && cost <= mana`` and
assigned Keys A.. sequentially over the survivors (so dropped entries
compacted the alphabet): under the ruling the profession gate stays
UPSTREAM (``get_castable_spell_types`` — a barbarian's C command still prints
"No spells to cast!" without opening any menu), the mana gate stays in
``cast_spell``'s prevalidation (the canonical "Thou dost not have enough
magic points!", still not executed), and the location gate
``canCastLocation(mt)`` (Constants.java:779-781 — the masks themselves are
unchanged Java truth) moves to ATTEMPT time via :func:`letter_resolution`.

Menu row format (Java truth, ``SpellInputProcessor.java:36-39``)::

    screen.log(String.format("%s - %s (%d)", key, spell, spell.getCost()));

``%s`` on the enum constant prints its NAME (e.g. ``PONTORI``), and the cost
is ALWAYS printed — 0 included — so a 0-cost spell renders ``A - PONTORI (0)``.

Refusal classification at attempt (:func:`letter_resolution`):

- a letter whose spell fails ``canCastLocation(context)`` -> ``"Not Here!"``;
  NOT executed (no cast, no mana), the caster stays active and the menu
  disarms (same shape as "Not a spell!") — no SpellResult is produced by
  the prompt layer;
- an unaffordable letter is still LISTED; the prompt flows refuse it AT
  LETTER SELECTION (F2 AMENDMENT 2026-11-15: right after
  :func:`letter_resolution` returns the spell, BEFORE the target/direction
  prompts) with ``cast_spell``'s canonical MP string — that prevalidation
  remains in ``cast_spell`` itself for direct-API callers — skipped only
  under the FULL MP cheat (``debug.apply_full_mp`` /
  ``debug.CHEATS.full_mp``);
- an out-of-list key (digits, or any letter not on the discipline's fixed
  A-P codes — with fixed per-discipline lists no in-range letter can be an
  out-of-discipline key) -> ``"Not a spell!"`` + disarm, the Java
  SpellInputProcessor.java:69-72 behavior retained for unknown letters.

Callers: CombatScreen.java:324 built the combat menu with MapType.combat;
SecondaryInputProcessor.java:283 passed the current map type; :443 passed
MapType.dungeon. py's seam: the prompt flows resolve the cleric-vs-wizard
discipline UPSTREAM — ``get_castable_spell_types`` (magic.py) for
single-discipline professions, the "[W]izard or [C]leric" prompt for
druid/ranger (each choice shows its own FIXED list, unchanged) — and hand
the resolved discipline into ``_ask_spell_code`` (screens/combat_screen.py
``_prompt_cast`` and combat/magic.py ``prompt_cast_party._ask_spell_code``).

Cheats (USER-DIRECTED GBC-RULES DEVIATION 2026-11-14, GBC cheat.c:414-825)
under the ruling:

- ``no_class`` — profession gate bypass ONLY: it widens
  ``get_castable_spell_types`` so both discipline menus open for any
  profession (the ``cast_spell`` per-spell gate matches at magic.py:290).
  Letters remain fixed.
- ``full_mp`` — MP refusal skipped: ``debug.apply_full_mp`` tops the caster
  up when the prompt opens, and the listed unaffordable letters never hit
  the mana gate.
"""

from typing import Any

from py_exodus.constants import MapType, Spell

#: USER-DIRECTED RULING (2026-11-15): fixed spell letters (B=APPAR_UNEM
#: always); availability refused at attempt — supersedes the Java
#: getCastables letter compaction (Constants.java:751-762) adopted
#: 2026-11-14.
LOCATION_REFUSAL = "Not Here!"
UNKNOWN_LETTER_REFUSAL = "Not a spell!"

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


def spell_menu_entries(
    discipline: str,
    caster: Any = None,
    cheats_ok: bool = True,
) -> list[tuple[str, Spell]]:
    """The discipline's FULL fixed cast menu: ``[(fixed_code, Spell), ...]``
    sorted by code — the enum's per-discipline alphabetical A-P ``code``.

    USER-DIRECTED RULING (2026-11-15): fixed spell letters (B=APPAR_UNEM
    always); availability refused at attempt — supersedes the Java
    getCastables letter compaction (Constants.java:751-762) adopted
    2026-11-14. Nothing here consults mana, profession or context: the
    profession gate lives upstream (``get_castable_spell_types``), the mana
    gate in ``cast_spell``'s prevalidation, the location gate in
    :func:`letter_resolution`. ``caster`` and ``cheats_ok`` are accepted for
    the 2026-11-14 call-shape compatibility and intentionally unused — no
    cheat reshapes a FIXED list (NOCLASS opens the upstream gate, FULL MP
    skips the downstream refusal).

    Unknown disciplines return an empty list; every real discipline has 16.
    """
    discipline = str(discipline).strip().lower()
    entries = [(s.code, s) for s in Spell if s.spell_type == discipline]
    entries.sort(key=lambda e: e[0])
    return entries


def spell_menu_prompt_lines(castables: list[tuple[str, Spell]]) -> list[str]:
    """Render the menu rows exactly as Java does (SpellInputProcessor.java:36-39):
    ``"{letter} - {SPELL_NAME} ({cost})"``, cost always printed, 0 included."""
    return [f"{letter} - {spell.name} ({spell.cost})" for letter, spell in castables]


def letter_resolution(
    entries: list[tuple[str, Spell]],
    letter: str,
    context: str,
) -> tuple[Spell, None] | tuple[None, str]:
    """Classify a pressed key against the FIXED entries for this context.

    Returns ``(Spell, None)`` when the attempt may proceed, or
    ``(None, refusal_message)``:

    - unknown key (not one of the entries' fixed codes) ->
      ``UNKNOWN_LETTER_REFUSAL`` ("Not a spell!") — Java
      SpellInputProcessor.java:69-72, retained;
    - a fixed code whose spell fails ``canCastLocation(mt)`` (mt from
      ``context``, Constants.java:779-781) -> ``LOCATION_REFUSAL``
      ("Not Here!") — refused AT ATTEMPT: not executed, no mana, the caster
      stays active, the menu disarms.

    The MP refusal deliberately does NOT live here: since F2 AMENDMENT
    (2026-11-15) the prompt flows check ``spell.cost <= mana`` right after
    this function returns the spell (BEFORE the target/direction prompts),
    so the menu can list unaffordable letters, the FULL MP cheat can skip
    that gate, and ``cast_spell``'s own prevalidation still covers
    direct-API callers.
    Raises ``ValueError`` for a context outside :data:`_CONTEXT_MAPTYPES`.
    """
    try:
        map_type = _CONTEXT_MAPTYPES[str(context).strip().lower()]
    except KeyError:
        raise ValueError(f"unknown spell-menu context: {context!r}") from None

    key = str(letter).strip().upper()
    found = next((s for code, s in entries if code == key), None)
    if found is None:
        # USER-DIRECTED RULING (2026-11-15): out-of-list keys keep Java's
        # "Not a spell!" branch (SpellInputProcessor.java:69-72).
        return None, UNKNOWN_LETTER_REFUSAL
    if not (map_type.mask & found.location_mask):
        # USER-DIRECTED RULING (2026-11-15): the location mask refuses AT
        # ATTEMPT ("Not Here!") instead of filtering the menu — the
        # getCastables letter compaction is superseded.
        return None, LOCATION_REFUSAL
    return found, None
