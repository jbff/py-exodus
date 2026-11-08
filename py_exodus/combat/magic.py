"""Magic & Spellcasting System for py-exodus (Ultima III).

Supports all 32 classic Ultima III spells (16 Clerical Prayers, 16 Wizard Sorceries),
validating profession permissions, MP costs, free-spell limits, and target conditions.
Connects with tactical combat (CombatArena) and overworld/dungeon exploration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import random
from typing import TYPE_CHECKING, Any

from py_exodus.combat.resolver import trace_projectile_path
from py_exodus.constants import (
    DUNGEON_LEVELS,
    Direction,
    MapType,
    Profession,
    Spell,
    Status,
    TileAttrib,
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
    "PABULUM": Spell.PABULUM,
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
) -> SpellResult:
    """Cast a spell by caster, validating MP, profession, target, and location."""
    # 1. Resolve spell enum
    resolved_spell = resolve_spell(spell, spell_type=spell_type, caster=caster)
    if resolved_spell is None:
        return SpellResult(success=False, message=f"Unknown spell: {spell}")

    # 2. Extract underlying Character and party
    caster_char: Character = getattr(caster, "character", caster)
    target_char: Character = getattr(target_member, "character", target_member) if target_member else caster_char
    active_party = party or getattr(caster, "party", None) or (arena.party if arena else None)

    # 3. Check caster incapacitation
    if caster_char.is_dead() or caster_char.is_disabled() or caster_char.status in (Status.DEAD, Status.ASH, Status.ASHES):
        return SpellResult(
            success=False,
            message=f"{caster_char.name} cannot cast spells while incapacitated.",
            spell=resolved_spell,
        )

    # 4. Check profession permission
    profession = caster_char.profession
    if not resolved_spell.can_cast(profession):
        prof_name = profession.value.capitalize() if isinstance(profession, Profession) else str(profession)
        return SpellResult(
            success=False,
            message=f"{prof_name} cannot cast {resolved_spell.name}.",
            spell=resolved_spell,
        )

    # 5. Check free combat spell limit (REPOND & PONTORI are once per combat encounter)
    is_free_combat_spell = resolved_spell in (Spell.REPOND, Spell.PONTORI)
    if arena is not None and is_free_combat_spell:
        if getattr(caster, "used_free_spell_in_combat", False):
            return SpellResult(
                success=False,
                message="Can't! Free combat prayer already used.",
                spell=resolved_spell,
            )

    # 6. Check magic points (MP)
    mp_cost = resolved_spell.cost
    if caster_char.mp < mp_cost:
        return SpellResult(
            success=False,
            message="Thou dost not have enough magic points!",
            spell=resolved_spell,
        )

    # 7. Check location permissions if environment is specified
    if arena is not None:
        if not (resolved_spell == Spell.DAG_ACRON or resolved_spell.can_cast_location(MapType.COMBAT)):
            return SpellResult(
                success=False,
                message=f"{resolved_spell.name} cannot be cast in combat!",
                spell=resolved_spell,
            )
    elif world_map is not None:
        m_type = getattr(world_map, "map_type", None)
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
            )

    # 8. Check direction requirement
    dir_val: Direction | None = None
    if target_dir is not None:
        dir_val = target_dir if isinstance(target_dir, Direction) else Direction.from_name_or_key(target_dir)

    if arena is not None and resolved_spell in DIRECTIONAL_SPELLS and dir_val is None:
        return SpellResult(
            success=False,
            message="Thou must indicate a direction to cast the spell!",
            spell=resolved_spell,
        )

    # 9. Pre-validate targeted restorative spells before consuming MP
    if resolved_spell == Spell.SANCTU:
        if target_char.is_dead() or target_char.status in (Status.DEAD, Status.ASH, Status.ASHES):
            return SpellResult(
                success=False,
                message=f"Cannot heal {target_char.name} (dead or ashes).",
                spell=resolved_spell,
            )
        if target_char.hp >= target_char.max_hp:
            return SpellResult(
                success=False,
                message=f"{target_char.name} is already at full health.",
                spell=resolved_spell,
            )

    elif resolved_spell == Spell.ALCORT:
        if target_char.status not in (Status.POISON, Status.POISONED):
            return SpellResult(
                success=False,
                message=f"{target_char.name} is not poisoned.",
                spell=resolved_spell,
            )

    elif resolved_spell == Spell.SANCTU_MANI:
        if target_char.is_dead() or target_char.status in (Status.DEAD, Status.ASH, Status.ASHES):
            return SpellResult(
                success=False,
                message=f"Cannot heal {target_char.name} (dead or ashes).",
                spell=resolved_spell,
            )
        if target_char.hp >= target_char.max_hp:
            return SpellResult(
                success=False,
                message=f"{target_char.name} is already at full health.",
                spell=resolved_spell,
            )

    elif resolved_spell == Spell.SURMANDUM:
        if target_char.status != Status.DEAD:
            return SpellResult(
                success=False,
                message=f"{target_char.name} is not dead.",
                spell=resolved_spell,
            )

    elif resolved_spell == Spell.ANJU_SERMANI:
        if target_char.status not in (Status.ASH, Status.ASHES):
            return SpellResult(
                success=False,
                message=f"{target_char.name} is not in ashes.",
                spell=resolved_spell,
            )

    # 10. Deduct MP and flag free spell usage
    caster_char.mp = max(0, caster_char.mp - mp_cost)
    if arena is not None and is_free_combat_spell:
        setattr(caster, "used_free_spell_in_combat", True)
        if hasattr(caster_char, "used_free_spell_in_combat"):
            setattr(caster_char, "used_free_spell_in_combat", True)

    # 11. Execute spell effect
    return _apply_spell_effect(
        spell=resolved_spell,
        caster_char=caster_char,
        target_char=target_char,
        caster_entity=caster,
        target_dir=dir_val,
        arena=arena,
        party=active_party,
    )


def _apply_spell_effect(
    spell: Spell,
    caster_char: Character,
    target_char: Character,
    caster_entity: Any,
    target_dir: Direction | None,
    arena: CombatArena | None,
    party: Party | None,
) -> SpellResult:
    """Dispatch and execute specific spell mechanics."""
    # --- Clerical Prayer Spells ---
    if spell == Spell.SANCTU:
        amount = min(target_char.max_hp - target_char.hp, random.randint(10, 25))
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
        amount = target_char.max_hp - target_char.hp
        target_char.hp = target_char.max_hp
        return SpellResult(
            success=True,
            message=f"{caster_char.name} casts Sanctu Mani! {target_char.name} fully restored (+{amount} HP).",
            healed=amount,
            spell=spell,
        )

    if spell == Spell.SURMANDUM:
        target_char.status = Status.GOOD
        target_char.hp = 1
        return SpellResult(
            success=True,
            message=f"{caster_char.name} casts Surmandum! {target_char.name} is resurrected!",
            healed=1,
            spell=spell,
        )

    if spell == Spell.ANJU_SERMANI:
        target_char.status = Status.GOOD
        target_char.hp = 1
        caster_char.wis = max(0, caster_char.wis - 5)
        return SpellResult(
            success=True,
            message=f"{caster_char.name} casts Anju Sermani! {target_char.name} recalled from ashes. {caster_char.name} lost 5 wisdom.",
            healed=1,
            spell=spell,
        )

    if spell == Spell.PONTORI:
        killed_count = 0
        if arena is not None:
            for m in arena.monsters:
                is_undead = (
                    getattr(m.definition, "undead", False)
                    or m.tile.lower() in UNDEAD_TILES
                    or any(t in m.name.lower() for t in UNDEAD_TILES)
                )
                if not m.is_dead and is_undead:
                    m.take_damage(m.hp)
                    arena.last_monster_death_pos = (m.x, m.y)
                    killed_count += 1
            return SpellResult(
                success=True,
                message=f"Holy power turns {killed_count} undead creatures!",
                targets_affected=killed_count,
                spell=spell,
            )
        return SpellResult(success=True, message="Holy power dispels evil.", spell=spell)

    if spell == Spell.REPOND:
        killed_count = 0
        if arena is not None:
            for m in arena.monsters:
                is_orc = m.tile.lower() in ORC_TILES or any(t in m.name.lower() for t in ORC_TILES)
                if not m.is_dead and is_orc:
                    m.take_damage(m.hp)
                    arena.last_monster_death_pos = (m.x, m.y)
                    killed_count += 1
            return SpellResult(
                success=True,
                message=f"Repond destroys {killed_count} goblinoid creatures!",
                targets_affected=killed_count,
                spell=spell,
            )
        return SpellResult(success=True, message="Repond resonates across the area.", spell=spell)

    # Directional projectile attacks (MITTAR, FULGAR, MENTAR, DECORP, EXCUUN)
    if spell in DIRECTIONAL_SPELLS:
        return _apply_projectile_attack(spell, caster_char, caster_entity, target_dir, arena)

    # Mass group damage spells (NOXUM, DAG_MENTAR, NECORP, ZXKUQYB, UNSPEAKABLE)
    if spell in (Spell.NOXUM, Spell.DAG_MENTAR, Spell.NECORP, Spell.ZXKUQYB, Spell.UNSPEAKABLE):
        return _apply_group_damage(spell, caster_char, arena)

    # Time Stop / Freeze (ALTAIR / ZOMM)
    if spell == Spell.ALTAIR:
        if arena is not None:
            arena.freeze_rounds = 3
            return SpellResult(
                success=True,
                message="Altair stops time! Enemies are frozen in place.",
                spell=spell,
            )
        if party is not None:
            setattr(party, "time_stop", 5)
        return SpellResult(success=True, message="Time stops momentarily.", spell=spell)

    # Teleport (DAG_ACRON / DAG ACRON)
    if spell == Spell.DAG_ACRON:
        if arena is not None:
            return _teleport_in_arena(arena, caster_entity, spell)
        if party is not None:
            # World map blink
            party.x = random.randint(5, 58)
            party.y = random.randint(5, 58)
            return SpellResult(success=True, message="Blink! Teleported across Sosaria.", spell=spell)
        return SpellResult(success=True, message="Teleportation energy ripples outward.", spell=spell)

    # Dungeon Teleport (LIB_REC)
    if spell == Spell.LIB_REC:
        return SpellResult(success=True, message="Party teleports to a new dungeon location.", spell=spell)

    # Dungeon Ascent / Descent / Exit
    if spell in (Spell.REC_SU, Spell.SUR_ACRON):
        if party is not None and getattr(party, "dungeon_level", 0) > 0:
            party.dungeon_level = max(0, party.dungeon_level - 1)
            return SpellResult(
                success=True,
                message=f"Ascended to dungeon level {party.dungeon_level}.",
                spell=spell,
            )
        return SpellResult(success=True, message="Mystical levitation lifts upward.", spell=spell)

    if spell in (Spell.REC_DU, Spell.DOR_ACRON):
        if party is not None:
            party.dungeon_level = min(DUNGEON_LEVELS, getattr(party, "dungeon_level", 0) + 1)
            return SpellResult(
                success=True,
                message=f"Descended to dungeon level {party.dungeon_level}.",
                spell=spell,
            )
        return SpellResult(success=True, message="Mystical descent shifts downward.", spell=spell)

    if spell == Spell.SEQUITU:
        if party is not None:
            party.dungeon_level = 0
            return SpellResult(success=True, message="Exited dungeon to surface.", spell=spell)
        return SpellResult(success=True, message="A path to the surface opens.", spell=spell)

    # Light / Torches (LORUM, LUMINAE, SOMINAE)
    if spell in (Spell.LORUM, Spell.LUMINAE, Spell.SOMINAE):
        duration = 100 if spell == Spell.SOMINAE else 25
        if party is not None:
            party.torch_duration = getattr(party, "torch_duration", 0) + duration
        return SpellResult(
            success=True,
            message=f"{spell.name.capitalize()} illuminates the darkness.",
            spell=spell,
        )

    # Food (PABULUM)
    if spell == Spell.PABULUM:
        if party is not None and hasattr(party, "members"):
            for m in party.members:
                m.food += random.randint(10, 25)
        else:
            caster_char.food += random.randint(10, 25)
        return SpellResult(
            success=True,
            message="Pabulum conjures nourishing rations for the journey!",
            spell=spell,
        )

    # Chest Disarm (APPAR_UNEM)
    if spell == Spell.APPAR_UNEM:
        # Safely disarms, opens, and collects chest contents (gold) without triggering traps
        found = False
        gold_found = 0
        if party is not None and hasattr(party, "dynamic_objects"):
            px = getattr(party, "x", 0)
            py = getattr(party, "y", 0)
            target_idx = -1
            for idx, obj in enumerate(party.dynamic_objects):
                ox = obj.get("x", -99)
                oy = obj.get("y", -99)
                tile = str(obj.get("tile", "")).lower()
                if tile == "chest" and abs(ox - px) <= 1 and abs(oy - py) <= 1:
                    target_idx = idx
                    break
            if target_idx >= 0:
                party.dynamic_objects.pop(target_idx)
                found = True
                gold_found = random.randint(50, 200)
                party.gold += gold_found

        if found:
            return SpellResult(
                success=True,
                message=f"Appar Unem safely disarms and opens the chest! Found {gold_found} gold.",
                spell=spell,
            )
        else:
            return SpellResult(
                success=False,
                message="Appar Unem: No chest nearby to disarm!",
                spell=spell,
            )

    # Overhead View / Peer (VIEDA)
    if spell == Spell.VIEDA:
        return SpellResult(
            success=True,
            message="Vieda reveals an overhead vision of the surroundings.",
            spell=spell,
        )

    # Wizard Divine Blessing (FAL_DIVI)
    if spell == Spell.FAL_DIVI:
        return SpellResult(
            success=True,
            message="Fal Divi invokes clerical divination.",
            spell=spell,
        )

    return SpellResult(success=True, message=f"{spell.name} cast successfully.", spell=spell)


def _apply_projectile_attack(
    spell: Spell,
    caster_char: Character,
    caster_entity: Any,
    target_dir: Direction | None,
    arena: CombatArena | None,
) -> SpellResult:
    """Execute directional projectile attacks against monsters in combat."""
    if spell == Spell.MITTAR:
        min_dmg, max_dmg = 16, 24
    elif spell == Spell.FULGAR:
        min_dmg, max_dmg = 32, 64
    elif spell == Spell.MENTAR:
        min_dmg, max_dmg = 32, max(32, caster_char.int)
    elif spell == Spell.DECORP:
        min_dmg, max_dmg = 128, 255
    elif spell == Spell.EXCUUN:
        min_dmg, max_dmg = 64, 255
    else:
        min_dmg, max_dmg = 10, 20

    if arena is not None and target_dir is not None:
        cx, cy = _get_caster_coords(arena, caster_entity)
        path = trace_projectile_path(
            combat_map=arena.combat_map,
            start_x=cx,
            start_y=cy,
            direction=target_dir,
            max_range=11,
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
            dmg = random.randint(min_dmg, max_dmg)
            target_m.take_damage(dmg)
            killed = target_m.is_dead
            if killed:
                arena.last_monster_death_pos = (target_m.x, target_m.y)
            msg = f"{spell.name.capitalize()} strikes {target_m.name} for {dmg} damage!{' Killed!' if killed else ''}"
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
        return SpellResult(
            success=True,
            message=f"{spell.name.capitalize()} fired {target_dir.name.lower()} into empty space.",
            damage=0,
            targets_affected=0,
            spell=spell,
            target_pos=path[-1] if path else None,
            projectile_path=path,
            hit=False,
        )

    dmg = random.randint(min_dmg, max_dmg)
    return SpellResult(
        success=True,
        message=f"{spell.name.capitalize()} unleashed for {dmg} damage.",
        damage=dmg,
        spell=spell,
    )


def _apply_group_damage(
    spell: Spell,
    caster_char: Character,
    arena: CombatArena | None,
) -> SpellResult:
    """Deal area damage to all active monsters in combat."""
    if arena is not None:
        total_dmg = 0
        affected_count = 0
        for m in list(arena.monsters):
            if not m.is_dead:
                if spell == Spell.NOXUM:
                    dmg = random.randint(24, max(24, caster_char.int))
                elif spell == Spell.DAG_MENTAR:
                    dmg = random.randint(32, max(32, caster_char.int))
                elif spell == Spell.NECORP:
                    dmg = random.randint(64, 128)
                elif spell == Spell.ZXKUQYB:
                    dmg = 255 if random.randint(0, 2) == 0 else max(15, m.hp * 3 // 4)
                elif spell == Spell.UNSPEAKABLE:
                    dmg = 255 if random.randint(0, 1) == 0 else max(15, m.hp // 2)
                else:
                    dmg = random.randint(20, 50)

                m.take_damage(dmg)
                if m.is_dead:
                    arena.last_monster_death_pos = (m.x, m.y)
                total_dmg += dmg
                affected_count += 1

        return SpellResult(
            success=True,
            message=f"{spell.name.capitalize()} blasts {affected_count} monsters for {total_dmg} total damage!",
            damage=total_dmg,
            targets_affected=affected_count,
            spell=spell,
        )

    return SpellResult(
        success=True,
        message=f"{spell.name.capitalize()} sweeps across the battlefield.",
        spell=spell,
    )


def _teleport_in_arena(
    arena: CombatArena,
    caster_entity: Any,
    spell: Spell,
) -> SpellResult:
    """Teleport caster to a random walkable open cell within the combat arena."""
    occupied = set(arena.player_positions.values())
    for m in arena.monsters:
        if not m.is_dead:
            occupied.add((m.x, m.y))

    open_cells: list[tuple[int, int]] = []
    for y in range(arena.combat_map.height):
        for x in range(arena.combat_map.width):
            if (x, y) not in occupied:
                tile = arena.combat_map.get_tile(x, y)
                if tile is not None:
                    attribs = getattr(tile, "attribs", TileAttrib.NONE)
                    if not bool(attribs & TileAttrib.UNWALKABLE):
                        open_cells.append((x, y))

    if not open_cells:
        return SpellResult(success=False, message="Failed to teleport! No open space.", spell=spell)

    nx, ny = random.choice(open_cells)
    _set_caster_coords(arena, caster_entity, nx, ny)
    return SpellResult(success=True, message=f"Blink! Teleported to ({nx}, {ny}).", spell=spell)


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
) -> None:
    """Standard party spellcasting prompt flow (overworld, town, dungeon).

    1. Cast: Which member? (1-4)
    2. If profession has multiple disciplines (Druid, Ranger): Spell Type? [W]izard or [C]leric
    3. [Wizard/Cleric] Spell? (A-P)
    4. If targeted restorative spell: On who? (1-4)
    5. Execute via cast_spell(...)
    """
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
        types = get_castable_spell_types(char.profession)
        if not types:
            prof_name = char.profession.value.capitalize() if hasattr(char.profession, "value") else str(char.profession)
            text_log.add_message(f"{char.name} ({prof_name}) cannot cast spells!")
            return

        def _ask_spell_code(discipline: str) -> None:
            type_label = "Wizard" if discipline == "wizard" else "Cleric"

            def _on_spell(code: str) -> None:
                code_upper = code.strip().upper()
                found_spell = resolve_spell(code_upper, spell_type=discipline, caster=caster_m)
                if found_spell is None:
                    text_log.add_message("Unknown spell!")
                    return

                if not found_spell.can_cast(char.profession):
                    text_log.add_message(f"{char.name} cannot cast {found_spell.name}!")
                    return

                if char.mp < found_spell.mp_cost:
                    text_log.add_message(f"Not enough MP! Need {found_spell.mp_cost} MP.")
                    return

                def _dispatch(target: Any | None = None) -> None:
                    res = cast_spell(
                        spell=found_spell,
                        caster=caster_m,
                        party=party,
                        world_map=world_map,
                        target_member=target,
                    )
                    text_log.add_message(res.message)
                    if res.success and audio is not None:
                        audio.play_sfx("magic")

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

    text_log.prompt("Cast: Which member? (1-4):", callback=_on_member, single_char=True)
