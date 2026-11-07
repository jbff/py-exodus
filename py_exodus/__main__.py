"""CLI entrypoint and main application loop for py-exodus (Ultima III)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pygame

from py_exodus.assets import AssetManager
from py_exodus.audio import AudioManager
from py_exodus.constants import (
    BASE_HEIGHT,
    BASE_WIDTH,
    SCALE,
)
from py_exodus.state_machine import StateMachine


class GameApp:
    """Main game application running the 60 FPS loop with integer 3x scaling."""

    def __init__(
        self,
        assets_dir: str = "src/main/resources/assets",
        scale: int = SCALE,
        headless: bool = False,
        sound_enabled: bool = True,
        **kwargs: Any,
    ) -> None:
        self.scale = scale
        self.width = BASE_WIDTH * scale
        self.height = BASE_HEIGHT * scale
        self.headless = headless
        self.running = False

        # Initialize pygame subsystems
        pygame.init()
        if not pygame.font.get_init():
            pygame.font.init()

        # Set up display surfaces
        self.internal_surface = pygame.Surface((BASE_WIDTH, BASE_HEIGHT))
        if not self.headless:
            try:
                self.display_surface = pygame.display.set_mode((self.width, self.height))
                pygame.display.set_caption("Ultima III: Exodus")
            except (pygame.error, Exception):
                self.headless = True
                self.display_surface = pygame.Surface((self.width, self.height))
        else:
            self.display_surface = pygame.Surface((self.width, self.height))

        # Assets and Audio
        self.assets_dir = Path(assets_dir)
        if not self.assets_dir.exists():
            alt = Path("assets")
            if alt.exists():
                self.assets_dir = alt

        self.asset_mgr = AssetManager(assets_dir=self.assets_dir)
        try:
            self.asset_mgr.load_tiles()
            self.asset_mgr.load_xml_definitions()
        except Exception:
            pass

        sound_path = self.assets_dir / "sound"
        self.audio = AudioManager(sound_dir=sound_path, enabled=sound_enabled)

        # State machine
        self.state_machine = StateMachine(
            asset_mgr=self.asset_mgr,
            audio=self.audio,
        )

        self.clock = pygame.time.Clock()

    def run(self, max_frames: int | None = None) -> None:
        """Execute the main game loop at 60 FPS."""
        self.running = True
        frame = 0

        while self.running:
            dt = self.clock.tick(60) / 1000.0

            # 1. Input Event Handling
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                    break
                self.state_machine.handle_event(event)

            if not self.running:
                break

            # 2. Logic Update
            self.state_machine.update(dt)

            # 3. Render directly onto display surface (or internal_surface if headless)
            render_surface = self.display_surface if not self.headless else self.internal_surface
            self.state_machine.render(render_surface)

            if not self.headless:
                pygame.display.flip()

            frame += 1
            if max_frames is not None and frame >= max_frames:
                break

    def stop(self) -> None:
        """Signal the game loop to terminate cleanly."""
        self.running = False

    def cleanup(self) -> None:
        """Cleanly tear down audio and pygame resources."""
        self.running = False
        if self.audio is not None:
            self.audio.stop_music()
        pygame.quit()


def main() -> None:
    """CLI execution entrypoint."""
    app = GameApp()
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        app.cleanup()
        sys.exit(0)


if __name__ == "__main__":
    main()
