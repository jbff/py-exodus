"""CLI entrypoint and main application loop for py-exodus (Ultima III)."""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from typing import Any

import pygame

from py_exodus import debug
from py_exodus.assets import AssetManager
from py_exodus.audio import AudioManager
from py_exodus.autoplay import AutoPlayController
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
        autoplay: bool = False,
        seed: int | None = None,
        trace: bool = False,
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

        from py_exodus.autoplay.tracer import RunTracer

        # --trace: record the autoplay run (starts when autoplay is enabled,
        # so F9-toggled runs are traced from the toggle on).
        self.tracer: RunTracer | None = RunTracer(enabled=autoplay, seed=seed) if trace else None
        self.autoplay = AutoPlayController(enabled=autoplay, tracer=self.tracer)
        self.state_machine.autoplay_enabled = self.autoplay.enabled
        self.state_machine.autoplay_step_interval = self.autoplay.step_interval
        self.clock = pygame.time.Clock()

    def run(self, max_frames: int | None = None) -> None:
        """Execute the main game loop at 60 FPS (closing the trace on exit or crash)."""
        try:
            self._run_loop(max_frames)
        except BaseException as exc:
            self._end_trace("CRASHED" if not isinstance(exc, KeyboardInterrupt) else "QUIT", exc)
            raise
        self._end_trace("QUIT")

    def _end_trace(self, default: str, exc: BaseException | None = None) -> None:
        if self.tracer is None or self.tracer.path is None:
            return
        party = getattr(self.state_machine.current_screen, "party", None)
        outcome = default
        if party is not None and getattr(party, "exodus_defeated", 0) > 0:
            outcome = "WON"
        elif party is not None and getattr(party, "members", None) and party.is_party_dead():
            outcome = "WIPED"
        self.tracer.end(outcome, party=party, exc=exc if outcome == "CRASHED" else None)
        print(f"[py-exodus] trace written: {self.tracer.path}")

    def _run_loop(self, max_frames: int | None = None) -> None:
        self.running = True
        frame = 0

        while self.running:
            dt = self.clock.tick(60) / 1000.0

            # 1. Input Event Handling
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                    break
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_F9:
                        self.autoplay.toggle()
                        if self.autoplay.enabled and self.tracer is not None:
                            self.tracer.activate()
                        self.state_machine.autoplay_enabled = self.autoplay.enabled
                        continue
                    if self.autoplay.enabled and event.key == pygame.K_LEFTBRACKET:
                        self.autoplay.adjust_speed(faster=False)
                        continue
                    if self.autoplay.enabled and event.key == pygame.K_RIGHTBRACKET:
                        self.autoplay.adjust_speed(faster=True)
                        continue
                self.state_machine.handle_event(event)

            if not self.running:
                break

            # 2. Logic Update
            self.autoplay.update(dt, self.state_machine)
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI flags.

    ``--debug`` enables the debug cheat harness (``py_exodus.debug``):
    F10 then opens the cheat menu on the game screens
    (USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): debug cheat harness
    (GBC cheat.c:414-825 docheat/domaxall)).
    """
    parser = argparse.ArgumentParser(
        prog="py-exodus",
        description="Ultima III: Exodus (python port)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable the debug cheat harness (F10 opens the cheat menu).",
    )
    parser.add_argument(
        "--autoplay",
        action="store_true",
        help="Start in Full Autoplay (Watch Mode); F9 toggles at runtime.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed Python's RNG for reproducible runs.",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Record the autoplay run to traces/trace_seed<N>_<time>.jsonl.gz.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """CLI execution entrypoint."""
    args = parse_args(argv)
    if args.seed is None:
        # Always have a printable, rerunnable seed.
        args.seed = random.SystemRandom().randrange(10_000_000, 99_999_999)
    random.seed(args.seed)
    print(f"[py-exodus] seed {args.seed} (rerun with --seed {args.seed})")
    debug.set_debug(args.debug)
    app = GameApp(autoplay=args.autoplay, seed=args.seed, trace=args.trace)
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        app.cleanup()
        sys.exit(0)


if __name__ == "__main__":
    main()
