"""Magic & Spellcasting System for py-exodus (Ultima III).
Supports all 32 classic Ultima III spells (16 Clerical Prayers, 16 Wizard Sorceries),
validating profession permissions, MP costs, free-spell limits, and target conditions.
Connects with tactical combat (CombatArena) and overworld/dungeon exploration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import random
from typing import TYPE_CHECKING, Any, Callable

from py_exodus import debug
from py_exodus.aura import AuraType
from py_exodus.combat.resolver import creature_wound_message, trace_projectile_path
from py_exodus.entities.character import EXP_CAP
from py_exodus.spell_menu import letter_resolution, spell_menu_entries, spell_menu_prompt_lines
from py_exodus.constants import (
    Direction,
    MapType,
    Profession,
    Spell,
    Status,
    Transport,
)

if TYPE_CHECKING:
    from py_exodus.combat.arena import CombatArena, CombatMonster
    from py_exodus.entities.character import Character
    from py_exodus.entities.party import Party, PartyMember


@dataclass
class SpellResult:
    """Outcome of casting a spell."""

    success: bool
    message: str = ""
    damage: int = 0
    healed: int = 0
    targets_affected: int = 0
    spell: Spell | None = None
    target_pos: tuple[int, int] | None = None
    projectile_path: list[tuple[int, int]] = field(default_factory=list)
    hit: bool = False
    # SEQUITU / SUR_ACRON-at-level-0 leave the dungeon; the owning screen
    # performs the transition (Java setScreen(dngScreen.gameScreen)).
    exit_dungeon: bool = False
    # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): VIEDA renders the
    # peer-gem view (GBC menucmd.c:1379-1390; LW UltimaSpellCombat.c
    # corroboration) — the flag tells the calling screen to open it, the same
    # convention as exit_dungeon.
    open_gem_view: bool = False
    # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): FAL_DIVI re-dispatches
    # to the cleric spell menu (GBC menucmd.c:1519-1530; LW
    # UltimaSpellCombat.c corroboration) — "cleric_menu" asks the calling
    # handler for one re-entry; combat consumes it as a no-op.
    followup: str | None = None
    # Task 4 (2026-11-14 combat-interaction-parity): EXECUTED vs REFUSED.
    # True (default) marks a cast that reached its effect branch — mana was
    # spent and the attempt happened, even when success is False (GBC
    # battle.c:1052-1060: the masskill-mismatch FAILED path returns 1, the
    # turn counts as spent). Only cast_spell's PRE-execution gates
    # (SpellUtil.java:24-76 semantics: unknown spell, incapacitation,
    # profession, missing direction, mana, used free spell, NEGATE aura,
    # location, restorative prevalidation) return executed=False — the
    # refusal happened BEFORE anything ran, so the caster stays active.
    executed: bool = True


# Spell name and synonym lookup table
SPELL_ALIASES: dict[str, Spell] = {
    # Cleric spells & aliases
    "SANCTU": Spell.SANCTU,
    "PURITU": Spell.ALCORT,
    "ALCORT": Spell.ALCORT,
    "SURMAND": Spell.SANCTU_MANI,
    "SANCTU_MANI": Spell.SANCTU_MANI,
    "SANCTUMANI": Spell.SANCTU_MANI,
    "ANCRON": Spell.SURMANDUM,
    "SURMANDUM": Spell.SURMANDUM,
    "APPAR UNM": Spell.ANJU_SERMANI,
    "APPAR_UNM": Spell.ANJU_SERMANI,
    "ANJU_SERMANI": Spell.ANJU_SERMANI,
    "ANJUSERMANI": Spell.ANJU_SERMANI,
    "PONTORI": Spell.PONTORI,
    "APPAR_UNEM": Spell.APPAR_UNEM,
    "APPARUNEM": Spell.APPAR_UNEM,
    "LUMINA": Spell.LUMINAE,
    "LUMINAE": Spell.LUMINAE,
    "REC_SU": Spell.REC_SU,
    "RECSU": Spell.REC_SU,
    "REC_DU": Spell.REC_DU,
    "RECDU": Spell.REC_DU,
    "LIB_REC": Spell.LIB_REC,
    "LIBREC": Spell.LIB_REC,
    "SEQUITU": Spell.SEQUITU,
    "SOMINAE": Spell.SOMINAE,
    "DAG LUMINA": Spell.SOMINAE,
    "DAG_LUMINA": Spell.SOMINAE,
    "VIEDA": Spell.VIEDA,
    "EXCUUN": Spell.EXCUUN,
    "ZXKUQYB": Spell.ZXKUQYB,
    # Wizard spells & aliases
    "REPOND": Spell.REPOND,
    "MITTAR": Spell.MITTAR,
    "LORUM": Spell.LORUM,
    "DOR_ACRON": Spell.DOR_ACRON,
    "DORACRON": Spell.DOR_ACRON,
    "SUR_ACRON": Spell.SUR_ACRON,
    "SURACRON": Spell.SUR_ACRON,
    "FULGAR": Spell.FULGAR,
    "DAG_ACRON": Spell.DAG_ACRON,
    "DAGACRON": Spell.DAG_ACRON,
    "MENTAR": Spell.MENTAR,
    "DAG_LORUM": Spell.DAG_LORUM,
    "DAGLORUM": Spell.DAG_LORUM,
    "FAL_DIVI": Spell.FAL_DIVI,
    "FALDIVI": Spell.FAL_DIVI,
    "NOXUM": Spell.NOXUM,
    "DECORP": Spell.DECORP,
    "ALTAIR": Spell.ALTAIR,
    "ZOMM": Spell.ALTAIR,
    "DAG_MENTAR": Spell.DAG_MENTAR,
    "DAGMENTAR": Spell.DAG_MENTAR,
    "NECORP": Spell.NECORP,
    "UNSPEAKABLE": Spell.UNSPEAKABLE,
}

UNDEAD_TILES = {
    "skeleton",
    "ghoul",
    "zombie",
    "ghost",
    "lich",
    "phantom",
    "wraith",
    "vampire",
    "undead",
}

# Java SpellUtil.spellRepond matches the single tile "orc" exactly; this
# broader historical set is kept for callers outside the spell table.
ORC_TILES = {
    "orc",
    "goblin",
    "troll",
    "gremlin",
}

DIRECTIONAL_SPELLS = {
    Spell.MITTAR,
    Spell.FULGAR,
    Spell.MENTAR,
    Spell.DECORP,
    Spell.EXCUUN,
    Spell.APPAR_UNEM,
}

# The spells whose Java effect branch is a directional bolt
# (SpellUtil.spellMagicAttack). APPAR_UNEM's effect reads the caster's own
# tile (SpellUtil.java:140-148) — the direction value is never used. Java
# still PROMPTS for it (SpellInputProcessor.java:52-61), but
# USER RULING 2026-11-11: the port drops that prompt — APPAR_UNEM casts
# without ever asking for a direction.
PROJECTILE_SPELLS = {Spell.MITTAR, Spell.FULGAR, Spell.MENTAR, Spell.DECORP, Spell.EXCUUN}

# Java spells whose effect branches never call finishPlayerTurn — the caster
# acts again — plus the effect-less REPLACE ME / default cases (SpellUtil.java
# 87-237). Only FAL_DIVI is actually castable in combat; the rest are
# dungeon/surface/dungeon-screen spells carried here for parity. DAG_LORUM
# is not here: LairWare's case 8 is an ordinary cast that spends the turn.
# ALTAIR is not here: LairWare's Altair (UltimaSpellCombat.c:238) is an
# ordinary cast and the combat loop goes on to plrdone, spending the turn.
NO_TURN_SPELLS = {
    Spell.LORUM,
    Spell.DAG_ACRON,
    Spell.REC_SU,
    Spell.REC_DU,
    Spell.SUR_ACRON,
    Spell.DOR_ACRON,
    Spell.LIB_REC,
    Spell.SEQUITU,
    Spell.VIEDA,
    Spell.LUMINAE,
    Spell.SOMINAE,
    Spell.FAL_DIVI,
}

TARGETED_MEMBER_SPELLS = {
    Spell.SANCTU,
    Spell.ALCORT,
    Spell.SANCTU_MANI,
    Spell.SURMANDUM,
    Spell.ANJU_SERMANI,
}


def get_castable_spell_types(profession: Profession | str) -> list[str]:
    """Return list of spell disciplines ('wizard', 'cleric') this profession can cast."""
    # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): debug cheat harness
    # (GBC cheat.c:414-825) — NOCLASS: ANY CHAR CAN CAST ANY SPELL; the
    # discipline filter hands out both spell lists to every profession.
    if debug.CHEATS.no_class:
        return ["wizard", "cleric"]
    if isinstance(profession, str):
        try:
            profession = Profession(profession.lower())
        except ValueError:
            return []
    types: list[str] = []
    if profession in (
        Profession.DRUID,
        Profession.ALCHEMIST,
        Profession.RANGER,
        Profession.WIZARD,
        Profession.LARK,
    ):
        types.append("wizard")
    if profession in (
        Profession.DRUID,
        Profession.RANGER,
        Profession.ILLUSIONIST,
        Profession.CLERIC,
        Profession.PALADIN,
    ):
        types.append("cleric")
    return types


def resolve_spell(
    spell: Spell | str,
    spell_type: str | None = None,
    caster: Character | PartyMember | None = None,
) -> Spell | None:
    """Resolve a Spell enum or string name/alias to a Spell."""
    if isinstance(spell, Spell):
        return spell
    if not isinstance(spell, str):
        return None

    key = spell.strip().upper().replace("-", "_")

    # If spell_type is not given, attempt to infer from caster's single discipline
    if spell_type is None and caster is not None:
        caster_char = getattr(caster, "character", caster)
        prof = getattr(caster_char, "profession", None)
        if prof is not None:
            disciplines = get_castable_spell_types(prof)
            if len(disciplines) == 1:
                spell_type = disciplines[0]

    # Full spell name or alias check first (exact name match)
    if key in SPELL_ALIASES:
        return SPELL_ALIASES[key]

    # If discipline is specified, look for matching code or name within that discipline
    if spell_type:
        st = spell_type.strip().lower()
        for s in Spell:
            if s.spell_type.lower() == st and (s.name == key or s.code == key):
                return s

    # Fallback search across all spells
    for s in Spell:
        if s.name == key or s.code == key:
            return s

    return None


def cast_spell(
    spell: Spell | str,
    caster: Character | PartyMember,
    target_dir: Direction | str | None = None,
    arena: CombatArena | None = None,
    world_map: Any | None = None,
    target_member: Character | PartyMember | None = None,
    party: Party | None = None,
    spell_type: str | None = None,
    position: tuple[int, int] | None = None,
    occupied: Callable[[int, int], bool] | None = None,
) -> SpellResult:
    """Cast a spell by caster, validating MP, profession, target, and location.

    ``position`` is the caster's tile on ``world_map`` when it is not the
    party's x/y (a town: the avatar walks the town map while party.x/y keep
    the overworld tile it was entered from). ``occupied(x, y)`` tells DAG
    ACRON which surface tiles hold a monster or an object.
    """
    # 1. Resolve spell enum
    resolved_spell = resolve_spell(spell, spell_type=spell_type, caster=caster)
    if resolved_spell is None:
        # REFUSED (Task 4): nothing resolved — nothing to execute.
        return SpellResult(success=False, message=f"Unknown spell: {spell}", executed=False)

    # 2. Extract underlying Character and party
    caster_char: Character = getattr(caster, "character", caster)
    target_char: Character = getattr(target_member, "character", target_member) if target_member else caster_char
    active_party = party or getattr(caster, "party", None) or (arena.party if arena else None)

    # 3. Check caster incapacitation — REFUSED (Task 4)
    if caster_char.is_dead() or caster_char.is_disabled() or caster_char.status in (Status.DEAD, Status.ASH, Status.ASHES):
        return SpellResult(
            success=False,
            message=f"{caster_char.name} cannot cast spells while incapacitated.",
            spell=resolved_spell,
            executed=False,
        )

    # 4. Check profession permission — REFUSED (Task 4)
    profession = caster_char.profession
    # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): debug cheat harness
    # (GBC cheat.c:414-825) — NOCLASS also opens the per-spell gate.
    if not resolved_spell.can_cast(profession) and not debug.CHEATS.no_class:
        prof_name = profession.value.capitalize() if isinstance(profession, Profession) else str(profession)
        return SpellResult(
            success=False,
            message=f"{prof_name} cannot cast {resolved_spell.name}.",
            spell=resolved_spell,
            executed=False,
        )

    # Direction for the cast: Java validates the direction requirement before
    # the mana check (SpellUtil.java:40-57). APPAR_UNEM is exempt per
    # USER RULING 2026-11-11 — Java's own effect ignores the value
    # (SpellUtil.java:140-148), so the prompt (and its requirement) is gone.
    dir_val: Direction | None = None
    if target_dir is not None:
        dir_val = target_dir if isinstance(target_dir, Direction) else Direction.from_name_or_key(target_dir)

    if resolved_spell in PROJECTILE_SPELLS and dir_val is None:
        # REFUSED (Task 4): Java's no-direction gate (SpellUtil.java:40-57) —
        # the directional-cancel case stays NON-consuming.
        return SpellResult(
            success=False,
            message="Thou must indicate a direction to cast the spell!",
            spell=resolved_spell,
            executed=False,
        )

    # 5. Check magic points (Java SpellUtil.java:57) — before free-spell use.
    mp_cost = resolved_spell.cost
    if caster_char.mp < mp_cost:
        # REFUSED (Task 4): mana gate fires BEFORE any effect — the caster
        # stays active (direct-API callers; prompt flows never hit it).
        return SpellResult(
            success=False,
            message="Thou dost not have enough magic points!",
            spell=resolved_spell,
            executed=False,
        )

    # 6. Free combat spell flag: Java sets usedFreeSpellInCombat BEFORE the
    #    NEGATE check, so a negated PONTORI/REPOND still burns the free spell
    #    (SpellUtil.java:62-76).
    # LairWare (UltimaSpellCombat.c:191, 253) tests the monster type
    # before the latch: a cast against the wrong type fails without spending
    # it, so it sets no flag here either.
    is_free_combat_spell = resolved_spell in (Spell.REPOND, Spell.PONTORI)
    if arena is not None and is_free_combat_spell and _masskill_targets(resolved_spell, arena):
        if getattr(caster, "used_free_spell_in_combat", False):
            # REFUSED (Task 4): "Can't!" used-free-spell gate
            # (SpellUtil.java:65-67) — pre-execution.
            return SpellResult(
                success=False,
                message="Can't!",
                spell=resolved_spell,
                executed=False,
            )
        setattr(caster, "used_free_spell_in_combat", True)
        if hasattr(caster_char, "used_free_spell_in_combat"):
            setattr(caster_char, "used_free_spell_in_combat", True)

    # 7. NEGATE aura blocks all casting with mana unspent
    #    (Java SpellUtil.java:73-76 — the deductive adjustMagic comes after).
    aura = getattr(active_party, "aura", None)
    if aura is not None and aura.get_type() == AuraType.NEGATE:
        # REFUSED (Task 4): negation gate fires before the deduct.
        return SpellResult(
            success=False,
            message="Spell is negated!",
            spell=resolved_spell,
            executed=False,
        )

    # 8. Check location permissions if environment is specified — REFUSED (Task 4)
    if arena is not None:
        if not resolved_spell.can_cast_location(MapType.COMBAT):
            return SpellResult(
                success=False,
                message=f"{resolved_spell.name} cannot be cast in combat!",
                spell=resolved_spell,
                executed=False,
            )
    elif world_map is not None:
        m_type = getattr(world_map, "map_type", None)
        if m_type is None and hasattr(world_map, "dmap"):
            m_type = getattr(world_map.dmap, "map_type", None)
        if isinstance(m_type, str):
            try:
                m_type = MapType(m_type)
            except ValueError:
                m_type = None
        if m_type and not resolved_spell.can_cast_location(m_type):
            return SpellResult(
                success=False,
                message=f"{resolved_spell.name} cannot be cast here!",
                spell=resolved_spell,
                executed=False,
            )

    # LairWare UltimaSpellCombat.c:212: `(Party[1] == 0x16 && Party[16] == 0)`
    # fails Dag Acron aboard ship while Exodus stands; refused at the attempt
    # (user ruling 3), no MP spent.
    if (
        resolved_spell == Spell.DAG_ACRON
        and getattr(active_party, "transport", None) == Transport.SHIP
        and not getattr(active_party, "exodus_defeated", 0)
    ):
        return SpellResult(success=False, message="Not Here!", spell=resolved_spell, executed=False)

    # LairWare DownLevel (UltimaSpellCombat.c:594-597): `if (dungeonLevel >
    # 6) { Failed(); return; }` - no going below the eighth level; refused at
    # the attempt (user ruling 3), no MP spent.
    if resolved_spell in (Spell.DOR_ACRON, Spell.REC_DU) and world_map is not None:
        dmap = getattr(world_map, "dmap", None)
        if dmap is not None and getattr(world_map, "z", 0) >= getattr(dmap, "levels", 8) - 1:
            return SpellResult(success=False, message="Not Here!", spell=resolved_spell, executed=False)

    # 9. Pre-validate targeted restorative spells before consuming MP
    # REFUSED (Task 4) on each branch: the gate fires BEFORE the effect and
    # the MP deduct.
    if resolved_spell == Spell.SANCTU:
        if target_char.is_dead() or target_char.status in (Status.DEAD, Status.ASH, Status.ASHES):
            return SpellResult(
                success=False,
                message=f"Cannot heal {target_char.name} (dead or ashes).",
                spell=resolved_spell,
                executed=False,
            )
        if target_char.hp >= target_char.max_hp:
            return SpellResult(
                success=False,
                message=f"{target_char.name} is already at full health.",
                spell=resolved_spell,
                executed=False,
            )

    elif resolved_spell == Spell.ALCORT:
        if target_char.status not in (Status.POISON, Status.POISONED):
            return SpellResult(
                success=False,
                message=f"{target_char.name} is not poisoned.",
                spell=resolved_spell,
                executed=False,
            )

    elif resolved_spell == Spell.SANCTU_MANI:
        if target_char.is_dead() or target_char.status in (Status.DEAD, Status.ASH, Status.ASHES):
            return SpellResult(
                success=False,
                message=f"Cannot heal {target_char.name} (dead or ashes).",
                spell=resolved_spell,
                executed=False,
            )
        if target_char.hp >= target_char.max_hp:
            return SpellResult(
                success=False,
                message=f"{target_char.name} is already at full health.",
                spell=resolved_spell,
                executed=False,
            )

    elif resolved_spell == Spell.SURMANDUM:
        if target_char.status != Status.DEAD:
            return SpellResult(
                success=False,
                message=f"{target_char.name} is not dead.",
                spell=resolved_spell,
                executed=False,
            )

    elif resolved_spell == Spell.ANJU_SERMANI:
        if target_char.status not in (Status.ASH, Status.ASHES):
            return SpellResult(
                success=False,
                message=f"{target_char.name} is not in ashes.",
                spell=resolved_spell,
                executed=False,
            )

    # 10. Deduct MP and flag free spell usage
    caster_char.mp = max(0, caster_char.mp - mp_cost)

    # 11. Execute spell effect
    return _apply_spell_effect(
        spell=resolved_spell,
        caster_char=caster_char,
        target_char=target_char,
        caster_entity=caster,
        target_dir=dir_val,
        arena=arena,
        party=active_party,
        world_map=world_map,
        position=position,
        occupied=occupied,
    )


def _masskill_targets(spell: Spell, arena: Any) -> list[Any]:
    """The living monsters REPOND (orcs, LW gMonType 0x30) or PONTORI (undead,
    the skeleton, LW 0x32) can strike in this fight."""
    out = []
    for m in getattr(arena, "monsters", ()):
        if m.is_dead:
            continue
        if spell == Spell.REPOND:
            ok = m.tile == "orc"
        else:
            ok = bool(
                getattr(getattr(m, "definition", None), "undead", False)
                or getattr(m, "undead", False)
            )
        if ok:
            out.append(m)
    return out


def _apply_spell_effect(
    spell: Spell,
    caster_char: Character,
    target_char: Character,
    caster_entity: Any,
    target_dir: Direction | None,
    arena: CombatArena | None,
    party: Party | None,
    world_map: Any | None = None,
    position: tuple[int, int] | None = None,
    occupied: Callable[[int, int], bool] | None = None,
) -> SpellResult:
    """Dispatch and execute specific spell mechanics."""
    # --- Clerical Prayer Spells ---
    if spell == Spell.SANCTU:
        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): heal is
        # randint(0, 20) + 10 (10-30), still clamped at missing HP, replacing
        # the Java Party.java:417-419 dice 75 + (rand.nextInt(256) % 25).
        # (GBC menucmd.c:1337-1420; LW UltimaSpellCombat.c:277-348)
        amount = min(target_char.max_hp - target_char.hp, random.randint(0, 20) + 10)
        target_char.hp += amount
        return SpellResult(
            success=True,
            message=f"{caster_char.name} casts Sanctu! {target_char.name} heals {amount} HP.",
            healed=amount,
            spell=spell,
        )

    if spell == Spell.ALCORT:
        target_char.status = Status.GOOD
        return SpellResult(
            success=True,
            message=f"{caster_char.name} casts Alcort! {target_char.name} is cured of poison.",
            spell=spell,
        )

    if spell == Spell.SANCTU_MANI:
        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): heal is
        # randint(0, 80) + 20 (20-100), capped at max HP, replacing the
        # full-restore-to-max behaviour. (GBC menucmd.c:1337-1420; LW
        # UltimaSpellCombat.c:277-348)
        amount = min(target_char.max_hp - target_char.hp, random.randint(0, 80) + 20)
        target_char.hp += amount
        return SpellResult(
            success=True,
            message=f"{caster_char.name} casts Sanctu Mani! {target_char.name} heals {amount} HP.",
            healed=amount,
            spell=spell,
        )

    if spell == Spell.SURMANDUM:
        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): 75% success leaves
        # the target GOOD; on 25% failure the target crumbles to ASHES (no
        # resurrect, no heal) instead of always resurrecting.
        # (GBC menucmd.c:1337-1420; LW UltimaSpellCombat.c:349-353)
        # LairWare UltimaSpellCombat.c:353 changes only 'D' -> 'G': the HP
        # stays as it was (0 after a death), as at the healer (user ruling
        # Q19; the port used to set 1).
        if random.random() < 0.75:
            target_char.status = Status.GOOD
            return SpellResult(
                success=True,
                message=f"{caster_char.name} casts Surmandum! {target_char.name} is resurrected!",
                healed=0,
                spell=spell,
            )
        target_char.status = Status.ASHES
        # EXECUTED (Task 4): the 25% fizzle rolled INSIDE the effect branch
        # (mana spent, target changed) — consumes despite success=False.
        return SpellResult(
            success=False,
            message=f"The spell fails! {target_char.name} crumbles to ashes!",
            spell=spell,
        )

    if spell == Spell.ANJU_SERMANI:
        # LairWare UltimaSpellCombat.c:374-375: 'A' -> 'G' with the HP left
        # as it was (user ruling Q19), and the caster loses 5 WIS. The WIS
        # floor at 0 stays (LW's unsigned byte wraps; ruled out as a bug).
        target_char.status = Status.GOOD
        caster_char.wis = max(0, caster_char.wis - 5)
        return SpellResult(
            success=True,
            message=f"{caster_char.name} casts Anju Sermani! {target_char.name} recalled from ashes. {caster_char.name} lost 5 wisdom.",
            healed=0,
            spell=spell,
        )

    if spell == Spell.PONTORI:
        killed_count = 0
        kill_lines: list[str] = []
        if arena is not None:
            # LairWare UltimaSpellCombat.c:253-256: `if (gMonType != 0x32)
            # { Failed(); return; }` before the g56E7 latch - the wrong type
            # fails (the turn is spent) and leaves the latch alone.
            if not _masskill_targets(spell, arena):
                return SpellResult(success=False, message="FAILED", spell=spell, executed=True)
            # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): per-battle 50% masskill flag gates PONTORI/REPOND (GBC funcs5.c:1354-1358; LW latch + cast-time roll is functionally equivalent)
            if not arena.masskill:
                # GBC faildat path: the gate fails the cast outright and the
                # latch stays unconsumed; mana was spent before the effect.
                # (GBC battle.c:1052; LW UltimaSpellCombat.c:192-268,475-495)
                # EXECUTED (Task 4): the cast ran its effect branch and GBC's
                # FAILED path returns 1 — the turn counts as spent even
                # though success is false.
                return SpellResult(success=False, message="FAILED", spell=spell, executed=True)
            # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): the Java
            # 50/65/80/100% turn ladder is deleted — the kill is level-
            # independent; each eligible undead dies on its own 75% roll
            # ((rnd)&0x03 != 0) via lethal damage against its CURRENT hp (the
            # rolled per-battle HP can exceed basehp). Kills keep the
            # established death-pos/EXP path. (GBC battle.c:821-844,
            # 1043-1053,1225-1239; LW UltimaSpellCombat.c:192-268,475-495)
            for m in list(arena.monsters):
                is_undead = (
                    getattr(getattr(m, "definition", None), "undead", False)
                    or getattr(m, "undead", False)
                )
                if (
                    is_undead
                    and not m.is_dead
                    and (random.randrange(256) & 0x03) != 0
                ):
                    m.take_damage(m.hp)
                    if m.is_dead:
                        arena.last_monster_death_pos = (m.x, m.y)
                        # XP flows with the kill path (killbaddie)
                        caster_char.exp = min(
                            EXP_CAP, caster_char.exp + getattr(m, "exp", 0)
                        )
                        killed_count += 1
                        kill_lines.append(_kill_line(m))
            # GBC consumes the latch after a gated-in cast (battle.c:1050,1232)
            arena.masskill = False
            summary = f"Holy power turns {killed_count} undead creatures!"
            return SpellResult(
                success=True,
                message="\n".join([*kill_lines, summary]),
                targets_affected=killed_count,
                spell=spell,
            )
        return SpellResult(success=True, message="Holy power dispels evil.", spell=spell)

    if spell == Spell.REPOND:
        killed_count = 0
        kill_lines = []
        if arena is not None:
            # LairWare UltimaSpellCombat.c:191: `(gMonType != 0x30)` fails
            # before the g5521 latch is touched.
            if not _masskill_targets(spell, arena):
                return SpellResult(success=False, message="FAILED", spell=spell, executed=True)
            # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): per-battle 50% masskill flag gates PONTORI/REPOND (GBC funcs5.c:1354-1358; LW latch + cast-time roll is functionally equivalent)
            if not arena.masskill:
                # GBC faildat path (battle.c:1235); mana was already spent.
                # EXECUTED (Task 4): reached the effect branch — consumes.
                return SpellResult(success=False, message="FAILED", spell=spell, executed=True)
            # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): same masskill
            # latch, same 75%-per-monster kill roll, level-independent — but
            # only the single tile "orc" is eligible (the port's goblinoid set
            # is kept). (GBC battle.c:821-844,1225-1239; LW
            # UltimaSpellCombat.c:192-268,475-495)
            for m in list(arena.monsters):
                if (
                    m.tile == "orc"
                    and not m.is_dead
                    and (random.randrange(256) & 0x03) != 0
                ):
                    m.take_damage(m.hp)
                    if m.is_dead:
                        arena.last_monster_death_pos = (m.x, m.y)
                        caster_char.exp = min(
                            EXP_CAP, caster_char.exp + getattr(m, "exp", 0)
                        )
                        killed_count += 1
                        kill_lines.append(_kill_line(m))
            # GBC consumes the latch after a gated-in cast (battle.c:1232)
            arena.masskill = False
            summary = f"Repond destroys {killed_count} goblinoid creatures!"
            return SpellResult(
                success=True,
                message="\n".join([*kill_lines, summary]),
                targets_affected=killed_count,
                spell=spell,
            )
        return SpellResult(success=True, message="Repond resonates across the area.", spell=spell)

    # Directional projectile attacks (MITTAR, FULGAR, MENTAR, DECORP, EXCUUN).
    # APPAR_UNEM shares the direction *prompt* but is a chest spell, not a bolt.
    if spell in PROJECTILE_SPELLS:
        return _apply_projectile_attack(spell, caster_char, caster_entity, target_dir, arena)

    # Mass group damage spells (NOXUM, DAG_MENTAR, NECORP, ZXKUQYB, UNSPEAKABLE)
    if spell in (Spell.NOXUM, Spell.DAG_MENTAR, Spell.NECORP, Spell.ZXKUQYB, Spell.UNSPEAKABLE):
        return _apply_group_damage(spell, caster_char, arena)

    # Time Stop / Freeze (ALTAIR / ZOMM)
    if spell == Spell.ALTAIR:
        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): stop time lasts 20
        # rounds (GBC menucmd.c:1551 — amended 2026-11-14: 20 rounds per LW
        # UltimaSpellCombat.c:238 + NES Bank0F.asm:3329 agreement); the older
        # Java 5-turn reading (SpellUtil.java:125-127) is superseded.
        aura = getattr(party, "aura", None)
        if aura is not None:
            aura.set(AuraType.QUICKNESS, 20)
        return SpellResult(
            success=True,
            message="Altair stops time!",
            spell=spell,
        )

    # Blink (DAG_ACRON): world map only — Java spellBlink (SpellUtil.java:105-107)
    if spell == Spell.DAG_ACRON:
        return _apply_spell_blink(world_map, party, occupied)

    # Dungeon elevation / teleport / exit: these run on the DungeonState the
    # screen passes as world_map (Java SpellUtil.spellYup/spellZdown/
    # spellLibRec/spellXit, SpellUtil.java:511-608). They are uncastable off
    # a dungeon by location mask, so a None dungeon is a silent success.
    if spell in (Spell.REC_SU, Spell.SUR_ACRON):
        if world_map is not None and hasattr(world_map, "spell_up"):
            evt = world_map.spell_up()
            return SpellResult(
                success=True,
                message=evt.message,
                spell=spell,
                exit_dungeon=evt.type.name == "EXIT_DUNGEON",
            )
        return SpellResult(success=True, spell=spell)

    if spell in (Spell.REC_DU, Spell.DOR_ACRON):
        if world_map is not None and hasattr(world_map, "spell_down"):
            evt = world_map.spell_down()
            return SpellResult(success=True, message=evt.message, spell=spell)
        return SpellResult(success=True, spell=spell)

    if spell == Spell.LIB_REC:
        if world_map is not None and hasattr(world_map, "spell_teleport"):
            evt = world_map.spell_teleport()
            return SpellResult(success=True, message=evt.message, spell=spell)
        return SpellResult(success=True, spell=spell)

    if spell == Spell.SEQUITU:
        if world_map is not None and hasattr(world_map, "spell_exit"):
            evt = world_map.spell_exit()
            return SpellResult(
                success=True,
                message=evt.message,
                spell=spell,
                exit_dungeon=evt.type.name == "EXIT_DUNGEON",
            )
        return SpellResult(success=True, spell=spell)

    # Light / Torches (LORUM, LUMINAE, SOMINAE)
    if spell in (Spell.LORUM, Spell.LUMINAE):
        # LairWare cases 2 and 19 (UltimaSpellCombat.c:203-206, 278-281)
        # write gTorch = 10. User rule 2026-11-25 (ledger P-18): no light
        # source ever shortens the light, so max(current, 10).
        if world_map is not None and hasattr(world_map, "torchtime"):
            world_map.torchtime = max(10, world_map.torchtime)
            return SpellResult(
                success=True,
                message=f"{spell.name.capitalize()} illuminates the darkness.",
                spell=spell,
            )
        # Java-parity boolean model fallback (DungeonScreen.isTorchOn).
        if world_map is not None and hasattr(world_map, "light_spell"):
            world_map.light_spell = True
        return SpellResult(
            success=True,
            message=f"{spell.name.capitalize()} illuminates the darkness.",
            spell=spell,
        )

    if spell == Spell.SOMINAE:
        # LairWare case 25 (UltimaSpellCombat.c:317-320): gTorch = 250 (not
        # the GBC 235). User rule 2026-11-25 (ledger P-18): no light source
        # ever shortens the light, so max(current, 250).
        if world_map is not None and hasattr(world_map, "torchtime"):
            world_map.torchtime = max(world_map.torchtime, 250)
        return SpellResult(success=True, spell=spell)

    # DAG LORUM: LairWare case 8 (UltimaSpellCombat.c:227-230) sets
    # gTorch = 250 wherever it is cast; only a dungeon keeps a light count.
    # User rule 2026-11-25 (P-18): never shorter than the light already lit.
    if spell == Spell.DAG_LORUM:
        if world_map is not None and hasattr(world_map, "torchtime"):
            world_map.torchtime = max(world_map.torchtime, 250)
        elif world_map is not None and hasattr(world_map, "light_spell"):
            world_map.light_spell = True
        return SpellResult(
            success=True,
            message="Dag Lorum illuminates the darkness.",
            spell=spell,
        )

    # Chest Disarm (APPAR_UNEM)
    if spell == Spell.APPAR_UNEM:
        # Java SpellUtil.java:140-148 — GameScreen/DungeonScreen.getChest at
        # the caster's own tile with disarmed=true; Java prompts a direction
        # but ignores its value (USER RULING 2026-11-11: no prompt at all).
        # Gold and the "The Chest Holds: N Gold" log come from the shared
        # chests pipeline (world/chests.py, Task 1).
        #
        # Screen split is Java truth: DungeonScreen.getChest
        # (DungeonScreen.java:1224-1252) scans ONLY the dungeon level's chest
        # tiles at (x, y, z), while GameScreen.getChest (GameScreen.java:
        # 1036-1074) scans the current map's chest objects at (x, y) and then
        # falls back to the chest tile rule. So a dungeon cast must not touch
        # the (stale) overworld party.x/y coordinates.
        from py_exodus.world.chests import ChestNotFound, open_chest, take_chest_object
        from py_exodus.world.map import DungeonTile

        member = caster_entity
        lines: list[str] = []
        opened = False

        px = getattr(party, "x", 0) if party is not None else 0
        py = getattr(party, "y", 0) if party is not None else 0
        if position is not None:
            px, py = position

        is_dungeon = world_map is not None and hasattr(world_map, "dmap") and hasattr(world_map, "z")

        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): APPAR_UNEM fails outright 25% of the time (GBC menucmd.c:1311-1313; LW UltimaSpellCombat.c:268-273 corroborates RandNum(0,255)&0x03)
        # GBC order: the chest check runs inside dogetchest BEFORE the roll
        # (menucmd.c:1054-1063), so a cast with no chest takes "Not Here!"
        # without consuming a roll — the fizzle only rolls when a chest IS
        # present. GBC clears the chest tile after the roll passes
        # (menucmd.c:1219-1233), so a failed cast leaves the chest in place,
        # and mana is spent on every cast either way (GBC deducts it at the
        # cast site before dogetchest, menucmd.c:1309 — the py pipeline
        # already charges mana unconditionally before the effect dispatch).
        def _appar_unem_fizzle() -> bool:
            # make_rnd(0) is a 0-255 draw: a 25%-of-words "0 after &0x03".
            return (random.randrange(256) & 0x03) == 0

        if is_dungeon:
            # DungeonScreen.getChest: the party's own dungeon tile only.
            dx = getattr(world_map, "x", px)
            dy = getattr(world_map, "y", py)
            if world_map.dmap.get_tile(dx, dy, world_map.z) == DungeonTile.CHEST:
                if _appar_unem_fizzle():
                    # GBC faildat2 (menucmd.c:153-156) prints "FAILED" and
                    # returns without opening; the chest tile is untouched.
                    # EXECUTED (Task 4): the fizzle rolled inside the effect
                    # branch — not a pre-execution refusal.
                    return SpellResult(success=False, message="FAILED", spell=spell)
                world_map.dmap.set_tile(dx, dy, world_map.z, DungeonTile.NOTHING)
                lines.extend(open_chest(party, member, dungeon=True, disarmed=True))
                opened = True
        else:
            # GameScreen.getChest: chest object exactly at the party's tile.
            if party is not None and hasattr(party, "dynamic_objects"):
                from py_exodus.entities.party import objects_on

                # Peek presence without mutating it: the fizzle must roll
                # before the chest object is taken (same GBC ordering as the
                # tile path above). Only this map's objects (user 2026-11-22).
                chest_object_present = any(
                    o.get("tile") == "chest" and o.get("x", -1) == px and o.get("y", -1) == py
                    for o in objects_on(party, world_map)
                )
                if chest_object_present and _appar_unem_fizzle():
                    # EXECUTED (Task 4): effect-branch fizzle (see above).
                    return SpellResult(success=False, message="FAILED", spell=spell)
                try:
                    take_chest_object(party, px, py, world_map)
                    lines.extend(open_chest(party, member, dungeon=False, disarmed=True))
                    opened = True
                except ChestNotFound:
                    pass

            # ... then the chest tile rule under the party (GameScreen.java
            # 1052-1059: replaceTile("floor") before the gold log).
            if not opened and world_map is not None and hasattr(world_map, "get_tile") and hasattr(world_map, "set_tile"):
                tile = world_map.get_tile(px, py)
                if tile is not None and (
                    getattr(tile, "name", "") == "chest"
                    or str(getattr(tile, "rule", "")).lower() == "chest"
                ):
                    if _appar_unem_fizzle():
                        # EXECUTED (Task 4): effect-branch fizzle (see above).
                        return SpellResult(success=False, message="FAILED", spell=spell)
                    from py_exodus.assets import TileDef

                    world_map.set_tile(px, py, TileDef(index=3, name="floor"))
                    lines.extend(open_chest(party, member, dungeon=False, disarmed=True))
                    opened = True

        if opened:
            return SpellResult(success=True, message="\n".join(lines), spell=spell)
        # EXECUTED (Task 4): the chest branch ran to its negative result
        # ("Not Here!") — in the world flow there is no turn to consume; in
        # combat it is unpromptable post-Task-3 and direct-API arena callers
        # now record the attempt as executed.
        return SpellResult(success=False, message="Not Here!", spell=spell)

    # Overhead View / Peer (VIEDA)
    if spell == Spell.VIEDA:
        return SpellResult(
            success=True,
            message="Vieda reveals an overhead vision of the surroundings.",
            spell=spell,
            open_gem_view=True,
        )

    # Wizard Divine Blessing (FAL_DIVI)
    if spell == Spell.FAL_DIVI:
        return SpellResult(
            success=True,
            message="Fal Divi invokes clerical divination.",
            spell=spell,
            followup="cleric_menu",
        )

    return SpellResult(success=True, message=f"{spell.name} cast successfully.", spell=spell)


def _lw_projectile_damage(spell: Spell, caster_char: Character) -> int:
    """LairWare Spell (UltimaSpellCombat.c:202-329): the damage each bolt
    hands to Projectile.

        case 1: /* Mittar */ Projectile(chnum, RandNum(0, 40) | 0x10);
        case 5: /* Fulgar */ Projectile(chnum, 75);
        case 7: /* Mentar */ Projectile(chnum, Player[rosNum][20]);   (INT)
        case 11: /* Decorp */ Projectile(chnum, 255);
        case 28: /* Excuun */ Projectile(chnum, 255);
    """
    if spell == Spell.MITTAR:
        return random.randint(0, 40) | 0x10
    if spell == Spell.FULGAR:
        return 75
    if spell == Spell.MENTAR:
        return caster_char.int
    return 255  # DECORP, EXCUUN


def _lw_damage_monster(arena: CombatArena, monster: Any, damage: int, caster_char: Character) -> bool:
    """LairWare DamageMonster (UltimaSpellCombat.c:734-756): nothing happens to
    Lord British (`gMonType != 0x26`); otherwise the monster dies when
    `MonsterHP - damage < 1` and the caster gets its experience (AddExp, capped
    at 9899), else it loses `damage` HP. Returns True on a kill."""
    if (getattr(monster, "tile", "") or "").lower() == "lord_british":
        return False
    monster.take_damage(damage)
    if not monster.is_dead:
        return False
    arena.last_monster_death_pos = (monster.x, monster.y)
    award = getattr(caster_char, "award_xp", None)
    if callable(award):
        award(getattr(monster, "exp", 0))
    else:
        caster_char.exp = min(EXP_CAP, caster_char.exp + getattr(monster, "exp", 0))
    return True


def _apply_projectile_attack(
    spell: Spell,
    caster_char: Character,
    caster_entity: Any,
    target_dir: Direction | None,
    arena: CombatArena | None,
) -> SpellResult:
    """Execute directional projectile attacks against monsters in combat.

    LairWare Projectile (UltimaSpellCombat.c:456-473): Shoot steps from the
    caster to the board edge over walls and members and hits the first
    monster; the damage comes from the spell (``_lw_projectile_damage``) and
    is applied by DamageMonster (``_lw_damage_monster``).
    """
    if arena is not None and target_dir is not None:
        cx, cy = _get_caster_coords(arena, caster_entity)
        path = trace_projectile_path(
            combat_map=arena.combat_map,
            start_x=cx,
            start_y=cy,
            direction=target_dir,
            max_range=11,
            attack_through_objects=True,
            monsters=arena.monsters,
            players=arena.player_positions,
        )

        target_m: CombatMonster | None = None
        for pt in path:
            for m in arena.monsters:
                if not m.is_dead and (m.x, m.y) == pt:
                    target_m = m
                    break
            if target_m is not None:
                break

        if target_m is not None:
            # LairWare Spell (UltimaSpellCombat.c:202-329) + DamageMonster
            # (734-756): Mittar RandNum(0, 40) | 0x10, Fulgar 75 (no fire
            # resistance), Mentar the caster's INT, Decorp and Excuun 255.
            dmg = _lw_projectile_damage(spell, caster_char)
            _lw_damage_monster(arena, target_m, dmg, caster_char)
            # Message parity (item 3): Java's ``castAt`` logs nothing about
            # the spell or the raw damage — the only player-visible line is
            # the same wound-status line melee prints, through
            # ``dealDamage`` → ``damageCreature`` (Utils.java:617-653):
            # "{name} Killed! Exp. {n}" on death (Utils.java:628), else the
            # tier text (Utils.java:634-650).
            msg = creature_wound_message(target_m)
            return SpellResult(
                success=True,
                message=msg,
                damage=dmg,
                targets_affected=1,
                spell=spell,
                target_pos=(target_m.x, target_m.y),
                projectile_path=path,
                hit=True,
            )
        # Message parity (item 3): Java's ``castAt`` returns NONE silently
        # with no creature on the ray (Utils.java:813-820) — no text.
        return SpellResult(
            success=True,
            message="",
            damage=0,
            targets_affected=0,
            spell=spell,
            target_pos=path[-1] if path else None,
            projectile_path=path,
            hit=False,
        )

    # No arena: nothing to hit (LW Projectile fails outside combat).
    return SpellResult(
        success=True,
        message="",
        damage=_lw_projectile_damage(spell, caster_char),
        spell=spell,
    )


def _kill_line(monster: Any) -> str:
    """Format the canonical per-creature kill line (Utils.java:628)."""
    name = getattr(monster, "name", "Creature")
    return f"{name} Killed! Exp. {getattr(monster, 'exp', 0)}"


def _apply_group_damage(
    spell: Spell,
    caster_char: Character,
    arena: CombatArena | None,
) -> SpellResult:
    """Deal area damage to all active monsters in combat.

    LairWare BigDeath (UltimaSpellCombat.c:475-495): each living monster is
    hit on `(RandNum(0, 255) & 0x03) != 0` (three in four) and takes the
    spell's damage through DamageMonster: Noxum 75, Dag Mentar twice the
    caster's INT, ZXKUQYB and the nameless P 255 (236, 239, 247, 355). A
    missed roll leaves the monster untouched. Necorp sets every living
    monster's HP to 5 (498-520).
    """
    if arena is not None:
        total_dmg = 0
        affected_count = 0
        kill_lines: list[str] = []
        for m in list(arena.monsters):
            if not m.is_dead:
                if spell == Spell.NECORP:
                    # LairWare Necorp (UltimaSpellCombat.c:500-521): every
                    # LIVING monster's HP becomes exactly 5, and that is all
                    # (no damage, no kill; user ruling 2026-11-25, ledger
                    # P-19, dropped the GBC monsterpower debuff).
                    m.hp = 5
                    affected_count += 1
                    continue
                # LairWare BigDeath (UltimaSpellCombat.c:482-483): the 75%
                # roll per monster. ZXKUQYB and the nameless P are
                # BigDeath(255) (user rulings 2026-11-15, 2026-11-22; Java's
                # hp*(3/4) quirk and 1/2-kill roll are gone).
                if (random.randrange(256) & 0x03) == 0:
                    continue  # missed: no damage at all
                if spell == Spell.NOXUM:
                    dmg = 75
                elif spell == Spell.DAG_MENTAR:
                    dmg = caster_char.int * 2
                else:
                    dmg = 255
                if (getattr(m, "tile", "") or "").lower() == "lord_british":
                    continue  # DamageMonster spares Lord British (738)
                if _lw_damage_monster(arena, m, dmg, caster_char):
                    kill_lines.append(_kill_line(m))
                total_dmg += dmg
                affected_count += 1

        if spell == Spell.NECORP:
            # No damage was dealt — NECORP only clamps hp to 5 and weakens.
            summary = f"Necorp weakens {affected_count} monsters to 5 hp!"
        elif spell in (Spell.ZXKUQYB, Spell.UNSPEAKABLE):
            # Ruling above: only kills count — survivors were untouched.
            summary = f"{spell.name.capitalize()} destroys {affected_count} monsters!"
        else:
            summary = (
                f"{spell.name.capitalize()} blasts {affected_count} monsters "
                f"for {total_dmg} total damage!"
            )
        return SpellResult(
            success=True,
            message="\n".join([*kill_lines, summary]),
            damage=total_dmg,
            targets_affected=affected_count,
            spell=spell,
        )

    return SpellResult(
        success=True,
        message=f"{spell.name.capitalize()} sweeps across the battlefield.",
        spell=spell,
    )


def _apply_spell_blink(
    world_map: Any,
    party: Any,
    occupied: Callable[[int, int], bool] | None = None,
) -> SpellResult:
    """DAG ACRON, LairWare Spell case 6 (UltimaSpellCombat.c:210-225):

        int matchValue = (Party[1] == 0x16) ? 0 : 4;
        while (value != matchValue) {
            xs = RandNum(0, gCurMapSize - 1); ys = RandNum(0, gCurMapSize - 1);
            value = GetXYVal(xs, ys);
        }
        xpos = xs; ypos = ys;

    Random tiles anywhere on the map until one is grass (open water aboard
    ship, allowed only once Exodus has fallen: the cast_spell gate). LW keeps
    its monsters in the map, so their tiles never match; ``occupied`` stands
    in for that. Off the Sosaria surface the location mask refuses the spell
    before it gets here (Ambrosia is a CITY map)."""
    if party is None or world_map is None or getattr(world_map, "map_type", None) not in (
        MapType.WORLD, MapType.WORLD.value,
    ):
        return SpellResult(success=False, message="FAILED", spell=Spell.DAG_ACRON)
    wanted = "water" if getattr(party, "transport", None) == Transport.SHIP else "grass"
    size_x = getattr(world_map, "width", 64)
    size_y = getattr(world_map, "height", 64)
    if not any(getattr(t, "name", "") == wanted for t in getattr(world_map, "tiles", ())):
        return SpellResult(success=False, message="FAILED", spell=Spell.DAG_ACRON)
    while True:
        x = random.randint(0, size_x - 1)
        y = random.randint(0, size_y - 1)
        tile = world_map.get_tile(x, y)
        if getattr(tile, "name", "") != wanted:
            continue
        if occupied is not None and occupied(x, y):
            continue
        party.x, party.y = x, y
        return SpellResult(success=True, spell=Spell.DAG_ACRON)


def _get_caster_coords(arena: CombatArena, caster_entity: Any) -> tuple[int, int]:
    """Retrieve grid position of caster in combat arena."""
    char = getattr(caster_entity, "character", caster_entity)
    for idx, member in enumerate(arena.party.members):
        if member is caster_entity or member.character is char:
            if idx in arena.player_positions:
                return arena.player_positions[idx]
    if hasattr(caster_entity, "combat_x") and caster_entity.combat_x is not None:
        return caster_entity.combat_x, caster_entity.combat_y
    return 5, 9


def _set_caster_coords(arena: CombatArena, caster_entity: Any, x: int, y: int) -> None:
    """Update grid position of caster in combat arena."""
    char = getattr(caster_entity, "character", caster_entity)
    for idx, member in enumerate(arena.party.members):
        if member is caster_entity or member.character is char:
            arena.player_positions[idx] = (x, y)
            member.combat_x = x
            member.combat_y = y
            member.x = x
            member.y = y
            return
    if hasattr(caster_entity, "combat_x"):
        caster_entity.combat_x = x
        caster_entity.combat_y = y


def prompt_cast_party(
    text_log: Any,
    party: Any,
    world_map: Any | None = None,
    audio: Any | None = None,
    view_callback: Any | None = None,
    exit_callback: Any | None = None,
    position: tuple[int, int] | None = None,
    occupied: Callable[[int, int], bool] | None = None,
) -> None:
    """Standard party spellcasting prompt flow (overworld, town, dungeon).

    1. Cast: Which member? (1-4)
    2. If profession has multiple disciplines (Druid, Ranger): Spell Type? [W]izard or [C]leric
    3. [Wizard/Cleric] Spell? (A-P) — the FULL FIXED list prints first and the
       letter lookup resolves through the SAME captured entries
       (Java SecondaryInputProcessor.java:283/443 + SpellInputProcessor
       .java:36-39); the menu's context is the caller's map type
       (``world``/``city``/``dungeon``/``shrine``, defaulting to ``world``).
    4. Directional spells prompt "Direction?" (Java SpellInputProcessor.java
       :52-59; the direction value is ignored where the spell needs none).
       APPAR_UNEM is exempt — USER RULING 2026-11-11: no direction prompt.
    5. If targeted restorative spell: On who? (1-4)
    6. Execute via cast_spell(...); VIEDA invokes ``view_callback`` and a
       dungeon-exiting spell invokes ``exit_callback``; a FAL_DIVI cast
       re-opens this whole member+spell prompt once (USER-DIRECTED GBC-RULES
       DEVIATION 2026-11-14, GBC menucmd.c:1519-1530).

    USER-DIRECTED RULING (2026-11-15): fixed spell letters (B=APPAR_UNEM
    always); availability refused at attempt — supersedes the Java
    getCastables letter compaction (Constants.java:751-762) adopted
    2026-11-14. Every prompt lists the discipline's FULL fixed A-P set
    (name + fixed letter + MP cost); letters NEVER move with mana or
    context. Refusals happen AT ATTEMPT:

    - a listed letter whose spell fails the context mask is refused by the
      prompt layer with "Not Here!" (letter_resolution) — NOT executed, no
      cast, no mana, and the menu disarms (no SpellResult produced here);
    - an unaffordable listed letter is refused AT LETTER SELECTION by the
      prompt layer (F2 AMENDMENT 2026-11-15: check lands right after the
      letter resolves, BEFORE any "Direction?"/"On who?" prompt) with the
      canonical "Thou dost not have enough magic points!" — the menu
      disarms. The mana prevalidation inside ``cast_spell`` stays for
      direct-API callers; the FULL MP cheat's prompt-open top-up
      (``debug.apply_full_mp``) — like the prompt-layer check itself —
      respects ``debug.CHEATS.full_mp`` and skips that gate;
    - a key outside the fixed A-P codes logs Java's canonical "Not a
      spell!" and DISARMS the menu (SpellInputProcessor.java:69-72 — py's
      Escape cancel stays silent, the harness-wide prompt convention, where
      Java's ESC would take the same out-of-range branch).
    """
    # Java builds the map with ``bm.getType()`` (SecondaryInputProcessor.java
    # :283; the dungeon screen passes MapType.dungeon, :443) — derive the
    # spell-menu context from the caller's map. A DungeonState wrapper is
    # unwrapped through ``dmap`` exactly as the cast_spell location gate does.
    map_type = getattr(world_map, "map_type", None)
    if map_type is None and hasattr(world_map, "dmap"):
        map_type = getattr(world_map.dmap, "map_type", None)
    map_type_value = getattr(map_type, "value", None) or map_type
    context = str(map_type_value).strip().lower() if map_type_value else "world"
    if context not in ("world", "city", "dungeon", "shrine"):
        context = "world"

    def _on_member(m_str: str) -> None:
        try:
            idx = int(m_str.strip()) - 1
            caster_m = party.get_member(idx)
        except ValueError:
            caster_m = None

        if caster_m is None:
            text_log.add_message("Invalid member #!")
            return

        if caster_m.is_dead():
            text_log.add_message(f"{caster_m.name} cannot cast while deceased!")
            return

        char = getattr(caster_m, "character", caster_m)
        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): debug cheat
        # harness (GBC cheat.c:414-825) — FULL MP: the caster's mana tops up
        # to max as the spell selection opens (the shared hook: this one
        # call covers the overworld, town and dungeon cast prompts).
        debug.apply_full_mp(caster_m)
        types = get_castable_spell_types(char.profession)
        if not types:
            # Java's canonical no-castables line: the same empty-castables
            # branch prints "No spells to cast!" in the overworld C-key flow
            # too (SecondaryInputProcessor.java:285,445).
            text_log.add_message("No spells to cast!")
            return

        def _ask_spell_code(discipline: str) -> None:
            type_label = "Wizard" if discipline == "wizard" else "Cleric"
            # USER-DIRECTED RULING (2026-11-15): fixed spell letters
            # (B=APPAR_UNEM always) — the full fixed A-P list is captured
            # once and drives BOTH the printed rows and the attempt-time
            # letter classification; py's seam: one FIXED list per RESOLVED
            # discipline (a druid's two menus are two calls, each showing
            # its own fixed letters).
            entries = spell_menu_entries(discipline)
            for line in spell_menu_prompt_lines(entries):
                text_log.add_message(line)

            def _on_spell(code: str) -> None:
                found_spell, refusal = letter_resolution(entries, code, context)
                if refusal is not None:
                    # Two prompt-layer refusals, both pre-execution (no
                    # SpellResult produced, no cast, no mana — USER-DIRECTED
                    # RULING 2026-11-15): "Not a spell!" for a key outside
                    # the fixed A-P codes and "Not Here!" for a fixed code
                    # whose spell fails canCastLocation(context)
                    # (Constants.java:779-781) — either way the menu
                    # DISARMS: input returns to the screen multiplexer with
                    # no row re-print, and the player re-presses C to see
                    # the list again (SpellInputProcessor.java:69-72).
                    text_log.add_message(refusal)
                    return

                # F2 AMENDMENT (USER-DIRECTED, 2026-11-15): the MP refusal
                # fires AT LETTER SELECTION — immediately after the letter
                # resolves, BEFORE the "Direction?" / "On who?" prompts —
                # with canonical SpellUtil.java:58 string. Previously the
                # target/direction prompt ran first and cast_spell's
                # prevalidation refused only after that selection; the
                # ruling moves the refusal up one step. The menu DISARMS on
                # the refusal (same shape as "Not Here!"/"Not a spell!": no
                # re-print, the player re-presses C). cast_spell's mana
                # prevalidation stays for direct-API callers; the FULL MP
                # cheat (CHEATS.full_mp — "MP NEVER DECREASES",
                # cheat.c:414-825) skips this gate, as its prompt-open
                # top-up already does.
                if not debug.CHEATS.full_mp and char.mp < found_spell.cost:
                    text_log.add_message("Thou dost not have enough magic points!")
                    return

                def _dispatch(target: Any | None = None, direction: Direction | None = None) -> None:
                    res = cast_spell(
                        spell=found_spell,
                        caster=caster_m,
                        party=party,
                        world_map=world_map,
                        target_member=target,
                        target_dir=direction,
                        position=position,
                        occupied=occupied,
                    )
                    if res.message:
                        text_log.add_message(res.message)
                    if res.success and audio is not None:
                        audio.play_sfx("magic")
                    if res.success and res.open_gem_view and view_callback is not None:
                        view_callback()
                    if res.success and getattr(res, "exit_dungeon", False) and exit_callback is not None:
                        exit_callback()
                    if res.success and res.followup == "cleric_menu":
                        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14):
                        # FAL_DIVI re-dispatches to the cleric spell menu
                        # (GBC menucmd.c:1519-1530; LW UltimaSpellCombat.c
                        # corroboration) — one re-entry at the member prompt,
                        # the same flow the C command uses. No automatic
                        # loop: the only followup emitter is FAL_DIVI (a
                        # wizard spell), so a single-discipline cleric/wizard
                        # re-entry cannot re-emit it; a druid choosing Wizard
                        # there starts a new cast, exactly as GBC's re-entry
                        # does.
                        _open_cast_prompt()

                if found_spell in TARGETED_MEMBER_SPELLS:
                    def _on_target(target_str: str) -> None:
                        try:
                            t_idx = int(target_str.strip()) - 1
                            target_m = party.get_member(t_idx)
                        except ValueError:
                            target_m = None
                        if target_m is None:
                            text_log.add_message("Invalid member #!")
                            return
                        _dispatch(target_m)

                    text_log.prompt("On who? (1-4):", callback=_on_target, single_char=True)
                elif found_spell in PROJECTILE_SPELLS:
                    text_log.add_message("Direction?")

                    def _on_dir(d_str: str) -> None:
                        d = Direction.from_name_or_key(d_str)
                        if d is None:
                            text_log.add_message("Invalid direction!")
                            return
                        _dispatch(direction=d)

                    text_log.prompt("Direction? (N,S,E,W):", callback=_on_dir, single_char=True)
                else:
                    _dispatch(None)

            text_log.prompt(f"{type_label} Spell? (A-P):", callback=_on_spell, single_char=True)

        if len(types) > 1:
            def _on_type(t_str: str) -> None:
                t = t_str.strip().upper()
                if t in ("W", "WIZARD"):
                    _ask_spell_code("wizard")
                elif t in ("C", "CLERIC"):
                    _ask_spell_code("cleric")
                else:
                    text_log.add_message("Invalid choice! Enter W or C.")

            text_log.prompt("Spell Type? [W]izard or [C]leric:", callback=_on_type, single_char=True)
        else:
            _ask_spell_code(types[0])

    def _open_cast_prompt() -> None:
        text_log.prompt("Cast: Which member? (1-4):", callback=_on_member, single_char=True)

    _open_cast_prompt()
