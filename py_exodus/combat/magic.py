"""Magic & Spellcasting System for py-exodus (Ultima III).
Supports all 32 classic Ultima III spells (16 Clerical Prayers, 16 Wizard Sorceries),
validating profession permissions, MP costs, free-spell limits, and target conditions.
Connects with tactical combat (CombatArena) and overworld/dungeon exploration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import random
from typing import TYPE_CHECKING, Any

from py_exodus.aura import AuraType
from py_exodus.combat.resolver import trace_projectile_path
from py_exodus.constants import (
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
    # SEQUITU / SUR_ACRON-at-level-0 leave the dungeon; the owning screen
    # performs the transition (Java setScreen(dngScreen.gameScreen)).
    exit_dungeon: bool = False


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
    # Java requires a direction prompt for APPAR_UNEM although the value is
    # then ignored (SpellUtil.java:40-50, SpellInputProcessor.java:52-59).
    Spell.APPAR_UNEM,
}

# The spells whose Java effect branch is a directional bolt
# (SpellUtil.spellMagicAttack).
_PROJECTILE_SPELLS = DIRECTIONAL_SPELLS - {Spell.APPAR_UNEM}

# Java spells whose effect branches never call finishPlayerTurn — the caster
# acts again — plus the effect-less REPLACE ME / default cases (SpellUtil.java
# 87-237). Only PABULUM and ALTAIR are actually castable in combat; the rest
# are dungeon/surface/dungeon-screen spells carried here for parity.
NO_TURN_SPELLS = {
    Spell.LORUM,
    Spell.PABULUM,
    Spell.ALTAIR,
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

    # Direction for the cast: Java validates the direction requirement before
    # the mana check (SpellUtil.java:40-57).
    dir_val: Direction | None = None
    if target_dir is not None:
        dir_val = target_dir if isinstance(target_dir, Direction) else Direction.from_name_or_key(target_dir)

    if resolved_spell in DIRECTIONAL_SPELLS and dir_val is None:
        return SpellResult(
            success=False,
            message="Thou must indicate a direction to cast the spell!",
            spell=resolved_spell,
        )

    # 5. Check magic points (Java SpellUtil.java:57) — before free-spell use.
    mp_cost = resolved_spell.cost
    if caster_char.mp < mp_cost:
        return SpellResult(
            success=False,
            message="Thou dost not have enough magic points!",
            spell=resolved_spell,
        )

    # 6. Free combat spell flag: Java sets usedFreeSpellInCombat BEFORE the
    #    NEGATE check, so a negated PONTORI/REPOND still burns the free spell
    #    (SpellUtil.java:62-76).
    is_free_combat_spell = resolved_spell in (Spell.REPOND, Spell.PONTORI)
    if arena is not None and is_free_combat_spell:
        if getattr(caster, "used_free_spell_in_combat", False):
            return SpellResult(
                success=False,
                message="Can't!",
                spell=resolved_spell,
            )
        setattr(caster, "used_free_spell_in_combat", True)
        if hasattr(caster_char, "used_free_spell_in_combat"):
            setattr(caster_char, "used_free_spell_in_combat", True)

    # 7. NEGATE aura blocks all casting with mana unspent
    #    (Java SpellUtil.java:73-76 — the deductive adjustMagic comes after).
    aura = getattr(active_party, "aura", None)
    if aura is not None and aura.get_type() == AuraType.NEGATE:
        return SpellResult(
            success=False,
            message="Spell is negated!",
            spell=resolved_spell,
        )

    # 8. Check location permissions if environment is specified
    if arena is not None:
        if not resolved_spell.can_cast_location(MapType.COMBAT):
            return SpellResult(
                success=False,
                message=f"{resolved_spell.name} cannot be cast in combat!",
                spell=resolved_spell,
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
    )


def _apply_spell_effect(
    spell: Spell,
    caster_char: Character,
    target_char: Character,
    caster_entity: Any,
    target_dir: Direction | None,
    arena: CombatArena | None,
    party: Party | None,
    world_map: Any | None = None,
) -> SpellResult:
    """Dispatch and execute specific spell mechanics."""
    # --- Clerical Prayer Spells ---
    if spell == Spell.SANCTU:
        # Java Party.java:417-419 — 75 + (rand.nextInt(256) % 25), capped at
        # max health (Party.java:432-435).
        amount = min(target_char.max_hp - target_char.hp, 75 + (random.randrange(256) % 25))
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
            level = caster_char.level
            for m in list(arena.monsters):
                # Java spellUndead (SpellUtil.java:387-438): the 50/65/80/100%
                # roll runs for every creature; only the undead may turn.
                turn = random.randrange(100) >= 50
                if level > 5:
                    turn = random.randrange(100) >= 35
                if level > 10:
                    turn = random.randrange(100) >= 20
                if level > 15:
                    turn = True

                is_undead = (
                    getattr(getattr(m, "definition", None), "undead", False)
                    or getattr(m, "undead", False)
                )
                if turn and is_undead and not m.is_dead:
                    m.take_damage(m.basehp)
                    if m.is_dead:
                        arena.last_monster_death_pos = (m.x, m.y)
                        # XP flows with the damage outcome (dealDamage path)
                        caster_char.exp = min(9999, caster_char.exp + getattr(m, "exp", 0))
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
            level = caster_char.level
            for m in list(arena.monsters):
                # Java spellRepond (SpellUtil.java:440-492): same roll ladder,
                # but only the single tile "orc" is eligible.
                turn = random.randrange(100) >= 50
                if level > 5:
                    turn = random.randrange(100) >= 35
                if level > 10:
                    turn = random.randrange(100) >= 20
                if level > 15:
                    turn = True

                if turn and m.tile == "orc" and not m.is_dead:
                    m.take_damage(m.basehp)
                    if m.is_dead:
                        arena.last_monster_death_pos = (m.x, m.y)
                        caster_char.exp = min(9999, caster_char.exp + getattr(m, "exp", 0))
                        killed_count += 1
            return SpellResult(
                success=True,
                message=f"Repond destroys {killed_count} goblinoid creatures!",
                targets_affected=killed_count,
                spell=spell,
            )
        return SpellResult(success=True, message="Repond resonates across the area.", spell=spell)

    # Directional projectile attacks (MITTAR, FULGAR, MENTAR, DECORP, EXCUUN).
    # APPAR_UNEM shares the direction *prompt* but is a chest spell, not a bolt.
    if spell in _PROJECTILE_SPELLS:
        return _apply_projectile_attack(spell, caster_char, caster_entity, target_dir, arena)

    # Mass group damage spells (NOXUM, DAG_MENTAR, NECORP, ZXKUQYB, UNSPEAKABLE)
    if spell in (Spell.NOXUM, Spell.DAG_MENTAR, Spell.NECORP, Spell.ZXKUQYB, Spell.UNSPEAKABLE):
        return _apply_group_damage(spell, caster_char, arena)

    # Time Stop / Freeze (ALTAIR / ZOMM)
    if spell == Spell.ALTAIR:
        # Java SpellUtil.java:125-127 — the QUICKNESS aura for 5 turns.
        aura = getattr(party, "aura", None)
        if aura is not None:
            aura.set(AuraType.QUICKNESS, 5)
        return SpellResult(
            success=True,
            message="Altair stops time!",
            spell=spell,
        )

    # Blink (DAG_ACRON): world map only — Java spellBlink (SpellUtil.java:105-107)
    if spell == Spell.DAG_ACRON:
        return _apply_spell_blink(world_map, caster_entity, party)

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
        # Java SpellUtil.java:89-94 (LORUM) and 161-163 (LUMINAE) both set
        # DungeonScreen.isTorchOn = true — the Task 10 boolean torch model.
        if world_map is not None and hasattr(world_map, "light_spell"):
            world_map.light_spell = True
        return SpellResult(
            success=True,
            message=f"{spell.name.capitalize()} illuminates the darkness.",
            spell=spell,
        )

    if spell == Spell.SOMINAE:
        # Java SpellUtil.java:187-189 — "REPLACE ME": the spell is a no-op
        # (mana is spent, nothing happens).
        return SpellResult(success=True, spell=spell)

    # Food (PABULUM)
    if spell == Spell.PABULUM:
        # Java SpellUtil.java:111-114 — getRandomBetween(5, 10) == 5..9 per member.
        def _food_roll() -> int:
            return random.randrange(10 - 5) + 5

        if party is not None and hasattr(party, "members"):
            for m in party.members:
                m.food += _food_roll()
        else:
            caster_char.food += _food_roll()
        return SpellResult(
            success=True,
            message="Pabulum conjures nourishing rations for the journey!",
            spell=spell,
        )

    # Chest Disarm (APPAR_UNEM)
    if spell == Spell.APPAR_UNEM:
        # Java SpellUtil.java:140-148 — GameScreen/DungeonScreen.getChest at
        # the caster's own tile with disarmed=true; the prompted direction is
        # ignored. Gold and the "The Chest Holds: N Gold" log come from the
        # shared chests pipeline (world/chests.py, Task 1).
        from py_exodus.world.chests import ChestNotFound, open_chest, take_chest_object
        from py_exodus.world.map import DungeonTile

        member = caster_entity
        lines: list[str] = []
        opened = False

        px = getattr(party, "x", 0) if party is not None else 0
        py = getattr(party, "y", 0) if party is not None else 0

        is_dungeon = world_map is not None and hasattr(world_map, "dmap") and hasattr(world_map, "z")

        # 1. Chest object at the party's tile (Java getChest drawables scan)
        if party is not None and hasattr(party, "dynamic_objects"):
            try:
                take_chest_object(party, px, py)
                lines.extend(open_chest(party, member, dungeon=is_dungeon, disarmed=True))
                opened = True
            except ChestNotFound:
                pass

        # 2. Chest tile at the party's position (GameScreen.getChest tile
        #    fallback) — dungeon chest tiles are cleared for the shared path.
        if not opened and world_map is not None:
            if hasattr(world_map, "dmap") and hasattr(world_map, "z"):
                tile = world_map.dmap.get_tile(
                    getattr(world_map, "x", px), getattr(world_map, "y", py),
                    world_map.z,
                )
                if tile == DungeonTile.CHEST:
                    world_map.dmap.set_tile(
                        getattr(world_map, "x", px), getattr(world_map, "y", py),
                        world_map.z, DungeonTile.NOTHING,
                    )
                    lines.extend(open_chest(party, member, dungeon=True, disarmed=True))
                    opened = True
            elif hasattr(world_map, "get_tile") and hasattr(world_map, "set_tile"):
                tile = world_map.get_tile(px, py)
                if tile is not None and (
                    getattr(tile, "name", "") == "chest"
                    or str(getattr(tile, "rule", "")).lower() == "chest"
                ):
                    from py_exodus.assets import TileDef

                    world_map.set_tile(px, py, TileDef(index=3, name="floor"))
                    lines.extend(open_chest(party, member, dungeon=False, disarmed=True))
                    opened = True

        if opened:
            return SpellResult(success=True, message="\n".join(lines), spell=spell)
        return SpellResult(success=False, message="Not Here!", spell=spell)

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


def _caster_damage(min_damage: int, max_damage: int) -> int:
    """Java Utils.castAt:816-828 — rand(min..max) inclusive; when not
    (0 <= min < max) the roll falls through to maxDamage."""
    if 0 <= min_damage < max_damage:
        return random.randint(min_damage, max_damage)
    return max_damage


def _get_random_between(low: int, high: int) -> int:
    """Java Utils.getRandomBetween:50-52 — rand.nextInt(high - low) + low,
    i.e. low..high-1."""
    if high > low:
        return random.randrange(high - low) + low
    return low


def _monster_resists_fire(monster: Any) -> bool:
    resists = getattr(getattr(monster, "definition", None), "resists", None)
    if resists is None:
        resists = getattr(monster, "resists", None)
    return resists == "fire"


def _apply_projectile_attack(
    spell: Spell,
    caster_char: Character,
    caster_entity: Any,
    target_dir: Direction | None,
    arena: CombatArena | None,
) -> SpellResult:
    """Execute directional projectile attacks against monsters in combat.

    Java truth: SpellUtil.spellMagicAttack → Utils.animateMagicAttack traces
    the ray with weaponCanAttackThroughObjects=true — spell bolts pass over
    walls — and Utils.castAt rolls the damage (with the FULGAR fire-resist).
    """
    if spell == Spell.MITTAR:
        min_dmg, max_dmg = 16, 24
    elif spell == Spell.FULGAR:
        min_dmg, max_dmg = 32, 64
    elif spell == Spell.MENTAR:
        min_dmg, max_dmg = 32, caster_char.int
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
            # Java castAt:815-820 — FULGAR is shrugged off by fire resistors.
            if spell == Spell.FULGAR and _monster_resists_fire(target_m):
                return SpellResult(
                    success=True,
                    message="Resisted!",
                    damage=0,
                    targets_affected=0,
                    spell=spell,
                    target_pos=(target_m.x, target_m.y),
                    projectile_path=path,
                    hit=False,
                )
            dmg = _caster_damage(min_dmg, max_dmg)
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

    dmg = _caster_damage(min_dmg, max_dmg)
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
    """Deal area damage to all active monsters in combat.

    Java truth: spellGroupDamage (SpellUtil.java:352-385) rolls
    Utils.getRandomBetween(min, max) per creature; useMaskOfMinax (646-688)
    and useRageOfGod (690-732) use their own per-creature rolls — with the
    ZXKUQYB ``hp * (3/4)`` == 0 bug ported verbatim.
    """
    if arena is not None:
        total_dmg = 0
        affected_count = 0
        for m in list(arena.monsters):
            if not m.is_dead:
                if spell == Spell.NOXUM:
                    dmg = _get_random_between(24, caster_char.int)
                elif spell == Spell.DAG_MENTAR:
                    dmg = _get_random_between(32, caster_char.int)
                elif spell == Spell.NECORP:
                    dmg = _get_random_between(64, 128)
                elif spell == Spell.ZXKUQYB:
                    if random.randrange(3) == 0:
                        dmg = 255
                    elif m.hp > 23:
                        dmg = m.hp * (3 // 4)  # Java integer 3/4 == 0 — ported bug
                    else:
                        dmg = 15
                elif spell == Spell.UNSPEAKABLE:
                    if random.randrange(2) == 0:
                        dmg = 255
                    elif random.randrange(2) == 0:
                        dmg = (m.hp - 23) if m.hp > 23 else 0
                    else:
                        dmg = m.hp // 2
                else:
                    dmg = _get_random_between(20, 50)

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


def _apply_spell_blink(
    world_map: Any,
    caster_entity: Any,
    party: Any,
) -> SpellResult:
    """Java SpellUtil.spellBlink (SpellUtil.java:267-350) — DOR/DAG ACRON's
    surface teleport: a random valid direction, the 0x10-grid distance walk,
    and a backward scan to the closest walkable tile. Non-surface screens log
    "Outdoors only!" instead."""
    target = caster_entity if getattr(caster_entity, "x", None) is not None else party
    if target is None:
        target = party

    if (
        world_map is None
        or getattr(world_map, "map_type", None) not in (MapType.WORLD, MapType.WORLD.value)
    ):
        return SpellResult(success=True, message="Outdoors only!", spell=Spell.DAG_ACRON)

    direction = random.choice(list(Direction))
    x = getattr(target, "x", 0)
    y = getattr(target, "y", 0)
    orig_x, orig_y = x, y

    var = x if direction.mask & (Direction.WEST.mask | Direction.EAST.mask) else y
    distance = var % 0x10
    if direction in (Direction.EAST, Direction.SOUTH):
        distance = 0x10 - distance

    # See if we move another 16 spaces over (Utils.rand.nextInt(diff * diff)).
    diff = 0x10 - distance
    if diff > 0 and random.randrange(diff * diff) > distance:
        distance += 0x10

    for _ in range(distance):
        x += direction.dx
        y += direction.dy

    reverse_dir = direction.reverse()
    remaining = distance
    while remaining > 0:
        tile = world_map.get_tile(x, y)
        if tile is None or not bool(getattr(tile, "attribs", TileAttrib.NONE) & TileAttrib.UNWALKABLE):
            break
        remaining -= 1
        x += reverse_dir.dx
        y += reverse_dir.dy

    tile = world_map.get_tile(x, y)
    if tile is not None and not bool(getattr(tile, "attribs", TileAttrib.NONE) & TileAttrib.UNWALKABLE):
        width = getattr(world_map, "width", None)
        height = getattr(world_map, "height", None)
        if (
            getattr(world_map, "border_behavior", None) == "wrap"
            and width is not None and height is not None
        ):
            x %= width
            y %= height
        # Java logs "Failed to teleport!" when the walk never left the tile.
        if (x, y) != (orig_x, orig_y):
            target.x = x
            target.y = y
            return SpellResult(success=True, spell=Spell.DAG_ACRON)
        return SpellResult(success=True, message="Failed to teleport!", spell=Spell.DAG_ACRON)
    return SpellResult(success=True, message="Failed to teleport!", spell=Spell.DAG_ACRON)


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
) -> None:
    """Standard party spellcasting prompt flow (overworld, town, dungeon).

    1. Cast: Which member? (1-4)
    2. If profession has multiple disciplines (Druid, Ranger): Spell Type? [W]izard or [C]leric
    3. [Wizard/Cleric] Spell? (A-P)
    4. Directional spells prompt "Direction?" (Java SpellInputProcessor.java
       :52-59; the direction value is ignored where the spell needs none)
    5. If targeted restorative spell: On who? (1-4)
    6. Execute via cast_spell(...); VIEDA invokes ``view_callback`` and a
       dungeon-exiting spell invokes ``exit_callback``.
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

                def _dispatch(target: Any | None = None, direction: Direction | None = None) -> None:
                    res = cast_spell(
                        spell=found_spell,
                        caster=caster_m,
                        party=party,
                        world_map=world_map,
                        target_member=target,
                        target_dir=direction,
                    )
                    if res.message:
                        text_log.add_message(res.message)
                    if res.success and audio is not None:
                        audio.play_sfx("magic")
                    if res.success and found_spell == Spell.VIEDA and view_callback is not None:
                        view_callback()
                    if res.success and getattr(res, "exit_dungeon", False) and exit_callback is not None:
                        exit_callback()

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
                elif found_spell in DIRECTIONAL_SPELLS:
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

    text_log.prompt("Cast: Which member? (1-4):", callback=_on_member, single_char=True)
