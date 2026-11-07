"""Audio manager for background music streaming and sound effects playback."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pygame

# Default track filename mapping (case-insensitive keys)
MUSIC_TRACKS: dict[str, str] = {
    "alive": "Alive.ogg",
    "castles": "Castles.ogg",
    "castle": "Castles.ogg",
    "combat": "Combat.ogg",
    "dungeon": "Dungeon.ogg",
    "exodus": "Exodus.ogg",
    "fanfare": "Fanfare.ogg",
    "rule britannia": "Rule Britannia.ogg",
    "rule brittania": "Rule Brittania.ogg",
    "shopping": "Shopping.ogg",
    "towns": "Towns.ogg",
    "town": "Towns.ogg",
    "wander": "Wander.ogg",
    "outside": "Wander.ogg",
    "sosaria": "Wander.ogg",
    "title_fade": "title_fade.ogg",
    "splash": "title_fade.ogg",
}


class AudioManager:
    """Manages background music playback and sound effect caching and playback."""

    def __init__(
        self,
        sound_dir: str | Path = "src/main/resources/assets/sound",
        music_volume: float = 0.5,
        sfx_volume: float = 0.7,
        enabled: bool = True,
    ) -> None:
        self.sound_dir = Path(sound_dir)
        if not self.sound_dir.exists():
            alt = Path("assets/sound")
            if alt.exists():
                self.sound_dir = alt

        self.music_volume = max(0.0, min(1.0, music_volume))
        self.sfx_volume = max(0.0, min(1.0, sfx_volume))
        self.enabled = enabled

        self.current_track: str | None = None
        self._sfx_cache: dict[str, Any] = {}
        self._mixer_initialized: bool = False

        if self.enabled:
            self._ensure_mixer()

    def _ensure_mixer(self) -> bool:
        """Ensure pygame.mixer is initialized safely without failing in headless mode."""
        if not self.enabled:
            return False
        try:
            if not hasattr(pygame, "mixer"):
                return False
            mixer = pygame.mixer
            if getattr(mixer, "get_init", None) is None:
                return False
            if mixer.get_init() is not None:
                self._mixer_initialized = True
                return True
            mixer.init()
            self._mixer_initialized = True
            return True
        except (NotImplementedError, AttributeError, ModuleNotFoundError, pygame.error, Exception):
            self._mixer_initialized = False
            return False

    def resolve_sound_file(self, filename_or_name: str) -> Path | None:
        """Locate sound file in sound directory with flexible matching."""
        raw = filename_or_name.strip()
        lower = raw.lower()

        # Check alias dictionary first
        if lower in MUSIC_TRACKS:
            candidate = self.sound_dir / MUSIC_TRACKS[lower]
            if candidate.exists():
                return candidate

        # Direct path check
        p = Path(raw)
        if p.exists() and p.is_file():
            return p

        # Check inside sound_dir
        direct = self.sound_dir / raw
        if direct.exists():
            return direct

        with_ogg = self.sound_dir / f"{raw}.ogg"
        if with_ogg.exists():
            return with_ogg

        with_mp3 = self.sound_dir / f"{raw}.mp3"
        if with_mp3.exists():
            return with_mp3

        # Case-insensitive search in directory
        if self.sound_dir.exists():
            for item in self.sound_dir.iterdir():
                stem = item.stem.lower()
                name = item.name.lower()
                if lower in (stem, name):
                    return item

        return None

    def play_music(
        self,
        track_name: str,
        loops: int = -1,
        volume: float | None = None,
    ) -> bool:
        """Stream and play background music in a loop."""
        if not self.enabled or not self._ensure_mixer():
            return False

        file_path = self.resolve_sound_file(track_name)
        if file_path is None or not file_path.exists():
            return False

        vol = self.music_volume if volume is None else max(0.0, min(1.0, volume))
        try:
            mixer = pygame.mixer
            music = mixer.music
            if self.current_track == str(file_path) and music.get_busy():
                return True

            music.load(str(file_path))
            music.set_volume(vol)
            music.play(loops)
            self.current_track = str(file_path)
            return True
        except (NotImplementedError, AttributeError, pygame.error, Exception):
            return False

    def stop_music(self) -> None:
        """Stop active background music."""
        if not self._mixer_initialized:
            return
        try:
            pygame.mixer.music.stop()
            self.current_track = None
        except (NotImplementedError, AttributeError, pygame.error, Exception):
            pass

    def pause_music(self) -> None:
        """Pause active background music."""
        if not self._mixer_initialized:
            return
        try:
            pygame.mixer.music.pause()
        except (NotImplementedError, AttributeError, pygame.error, Exception):
            pass

    def unpause_music(self) -> None:
        """Unpause background music."""
        if not self._mixer_initialized:
            return
        try:
            pygame.mixer.music.unpause()
        except (NotImplementedError, AttributeError, pygame.error, Exception):
            pass

    def set_music_volume(self, volume: float) -> None:
        """Set music volume between 0.0 and 1.0."""
        self.music_volume = max(0.0, min(1.0, volume))
        if self._mixer_initialized:
            try:
                pygame.mixer.music.set_volume(self.music_volume)
            except (NotImplementedError, AttributeError, pygame.error, Exception):
                pass

    def get_music_volume(self) -> float:
        """Return current music volume."""
        return self.music_volume

    def play_sfx(self, sfx_name: str, volume: float | None = None) -> bool:
        """Load and play a sound effect with caching."""
        if not self.enabled or not self._ensure_mixer():
            return False

        snd = self._sfx_cache.get(sfx_name.lower())
        if snd is None:
            file_path = self.resolve_sound_file(sfx_name)
            if file_path is None or not file_path.exists():
                return False
            try:
                snd = pygame.mixer.Sound(str(file_path))
                self._sfx_cache[sfx_name.lower()] = snd
            except (NotImplementedError, AttributeError, pygame.error, Exception):
                return False

        vol = self.sfx_volume if volume is None else max(0.0, min(1.0, volume))
        try:
            snd.set_volume(vol)
            snd.play()
            return True
        except (NotImplementedError, AttributeError, pygame.error, Exception):
            return False

    def set_sfx_volume(self, volume: float) -> None:
        """Set default sound effect volume between 0.0 and 1.0."""
        self.sfx_volume = max(0.0, min(1.0, volume))
        for snd in self._sfx_cache.values():
            try:
                snd.set_volume(self.sfx_volume)
            except (NotImplementedError, AttributeError, pygame.error, Exception):
                pass

    def get_sfx_volume(self) -> float:
        """Return current SFX volume."""
        return self.sfx_volume
