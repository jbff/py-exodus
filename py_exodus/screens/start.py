"""Start and title screen for Ultima III: Exodus."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pygame

from py_exodus.constants import (
    BASE_HEIGHT,
    BASE_WIDTH,
    ArmorType,
    Profession,
    Race,
    Sex,
    Status,
    Transport,
    WeaponType,
)
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.screens.base import BaseScreen
from py_exodus.ui.text_log import (
    EGA_BLACK,
    EGA_BRIGHT_CYAN,
    EGA_BRIGHT_GREEN,
    EGA_BRIGHT_RED,
    EGA_DARK_GRAY,
    EGA_LIGHT_GRAY,
    EGA_WHITE,
    EGA_YELLOW,
    get_hud_font,
)

if TYPE_CHECKING:
    from py_exodus.assets import AssetManager
    from py_exodus.audio import AudioManager


def create_default_starter_party() -> Party:
    """Create a balanced classic 4-member party for immediate play."""
    c1 = Character(
        name="Fighter",
        sex=Sex.MALE,
        race=Race.HUMAN,
        profession=Profession.PALADIN,
        strength=20,
        dexterity=15,
        intelligence=10,
        wisdom=15,
        hp=150,
        max_hp=150,
        exp=0,
        weapon=WeaponType.SWORD,
        armor=ArmorType.LEATHER,
    )
    c2 = Character(
        name="Cleric",
        sex=Sex.FEMALE,
        race=Race.BOBIT,
        profession=Profession.CLERIC,
        strength=12,
        dexterity=14,
        intelligence=10,
        wisdom=24,
        hp=100,
        max_hp=100,
        mp=24,
        exp=0,
        weapon=WeaponType.MACE,
        armor=ArmorType.CLOTH,
    )
    c3 = Character(
        name="Wizard",
        sex=Sex.MALE,
        race=Race.ELF,
        profession=Profession.WIZARD,
        strength=10,
        dexterity=14,
        intelligence=25,
        wisdom=11,
        hp=100,
        max_hp=100,
        mp=25,
        exp=0,
        weapon=WeaponType.DAGGER,
        armor=ArmorType.CLOTH,
    )
    c4 = Character(
        name="Thief",
        sex=Sex.FEMALE,
        race=Race.FUZZY,
        profession=Profession.THIEF,
        strength=12,
        dexterity=25,
        intelligence=12,
        wisdom=11,
        hp=120,
        max_hp=120,
        exp=0,
        weapon=WeaponType.SLING,
        armor=ArmorType.LEATHER,
    )
    return Party(
        members=[c1, c2, c3, c4],
        x=45,
        y=18,  # Near Castle Britannia on Sosaria
        gold=200,
        food=400,
        torch_duration=100,
    )


class StartScreen(BaseScreen):
    """Title and main menu screen for py-exodus."""

    def __init__(
        self,
        asset_mgr: AssetManager | None = None,
        audio: AudioManager | None = None,
        party: Party | None = None,
        return_screen: BaseScreen | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(return_screen=return_screen, **kwargs)
        self.asset_mgr = asset_mgr
        self.audio = audio
        self.party = party

        self.options = [
            ("Journey Onward", self._start_journey),
            ("New Game / Roster", self._new_game),
            ("Spellbook Manual", self._open_book),
        ]
        self.selected_idx = 0
        self.anim_time: float = 0.0

        # Background surfaces
        self.bg_image: pygame.Surface | None = None
        self.border_image: pygame.Surface | None = None
        self._load_visual_assets()

    def _load_visual_assets(self) -> None:
        if self.asset_mgr is None:
            return
        try:
            from py_exodus.assets import load_image_surface

            demon_path = self.asset_mgr.resolve_path("graphics", "demon.png")
            if demon_path.exists():
                self.bg_image = load_image_surface(demon_path)
            border_path = self.asset_mgr.resolve_path("graphics", "splash_border.png")
            if border_path.exists():
                self.border_image = load_image_surface(border_path)
        except Exception:
            pass

    def on_enter(self) -> None:
        super().on_enter()
        if self.audio is not None:
            self.audio.play_music("title_fade")

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return

        if event.key in (pygame.K_UP, pygame.K_w):
            self.selected_idx = (self.selected_idx - 1) % len(self.options)
            if self.audio is not None:
                self.audio.play_sfx("walk_normal")
        elif event.key in (pygame.K_DOWN, pygame.K_s):
            self.selected_idx = (self.selected_idx + 1) % len(self.options)
            if self.audio is not None:
                self.audio.play_sfx("walk_normal")
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            if self.audio is not None:
                self.audio.play_sfx("trigger")
            self.options[self.selected_idx][1]()
        elif event.key in (pygame.K_1, pygame.K_j):
            self.selected_idx = 0
            self._start_journey()
        elif event.key in (pygame.K_2, pygame.K_m, pygame.K_n):
            self.selected_idx = 1
            self._new_game()
        elif event.key in (pygame.K_3, pygame.K_b):
            self.selected_idx = 2
            self._open_book()

    def update(self, dt: float) -> None:
        self.anim_time += dt

    def render(self, surface: pygame.Surface) -> None:
        w, h = surface.get_width(), surface.get_height()
        surface.fill(EGA_BLACK)

        # Draw decorative background if available
        if self.bg_image is not None:
            scaled_bg = pygame.transform.scale(self.bg_image, (w, h))
            surface.blit(scaled_bg, (0, 0))

        # Title banner
        title_font = get_hud_font(size=20)
        sub_font = get_hud_font(size=14)
        info_font = get_hud_font(size=10)

        title_surf = title_font.render("ULTIMA III: EXODUS", True, EGA_YELLOW)
        surface.blit(
            title_surf,
            ((w - title_font.size("ULTIMA III: EXODUS")[0]) // 2, 20),
        )

        sub_surf = sub_font.render("From the depths of hell... he comes!", True, EGA_BRIGHT_RED)
        surface.blit(
            sub_surf,
            ((w - sub_font.size("From the depths of hell... he comes!")[0]) // 2, 50),
        )

        # Menu options
        menu_y = 90
        for i, (label, _) in enumerate(self.options):
            is_sel = (i == self.selected_idx)
            color = EGA_BRIGHT_GREEN if is_sel else EGA_LIGHT_GRAY
            prefix = " > " if is_sel else "   "
            opt_surf = sub_font.render(f"{prefix}{label}", True, color)
            surface.blit(opt_surf, (80, menu_y + i * 24))

        # Footer
        footer = "Use Arrows/Enter or 1-3 to select"
        foot_surf = info_font.render(footer, True, EGA_DARK_GRAY)
        surface.blit(foot_surf, ((w - info_font.size(footer)[0]) // 2, h - 25))

    def _start_journey(self) -> None:
        """Begin or resume the adventure in the overworld."""
        party = self.party
        if party is None:
            # Attempt to load binary or json party, fallback to default
            try:
                from py_exodus.save_system import SaveSystem

                save_p = Path("assets/data/party.ult")
                if not save_p.exists():
                    save_p = Path("src/main/resources/assets/data/party.ult")
                if save_p.exists():
                    party = SaveSystem.load_binary_party(save_p)
            except Exception:
                party = None

        if party is None or not party.members:
            party = create_default_starter_party()

        self.party = party

        from py_exodus.screens.overworld import OverworldScreen

        overworld = OverworldScreen(
            party=self.party,
            asset_mgr=self.asset_mgr,
            audio=self.audio,
            return_screen=self,
            manager=self.manager,
        )
        if self.manager is not None:
            self.manager.set_screen(overworld)
        else:
            self.next_screen = overworld
            self.is_finished = True

    def _new_game(self) -> None:
        """Create fresh party and begin journey."""
        self.party = create_default_starter_party()
        self._start_journey()

    def _open_book(self) -> None:
        """Open spellbook reference manual screen."""
        from py_exodus.screens.book import BookScreen

        book = BookScreen(return_screen=self, manager=self.manager)
        if self.manager is not None:
            self.manager.push_screen(book)
        else:
            self.next_screen = book
            self.is_finished = True
