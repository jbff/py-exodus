"""Where py-exodus keeps the player's files.

Saves live in the per-user data folder of each system, so the game works the
same from a source checkout, a packaged app or an install folder that is
read-only:

- Windows: ``%APPDATA%\\py-exodus``
- macOS: ``~/Library/Application Support/py-exodus``
- Linux and others: ``$XDG_DATA_HOME/py-exodus`` (``~/.local/share/py-exodus``)

``PY_EXODUS_SAVE_DIR`` overrides it (a relative value is taken from the
current directory each time). The test suite sets it to ``saves`` so tests
keep writing under their own temporary directories, never the player's.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "py-exodus"
SAVE_DIR_ENV = "PY_EXODUS_SAVE_DIR"
PARTY_FILE = "party.json"
ROSTER_FILE = "roster.json"

#: The old place: ``saves/`` in the source checkout (before 2026-11-26).
LEGACY_SAVE_DIR = Path(__file__).resolve().parent.parent / "saves"


def user_data_dir() -> Path:
    """The per-user data folder for this system."""
    home = Path.home()
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA")
        return (Path(base) if base else home / "AppData" / "Roaming") / APP_NAME
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else home / ".local" / "share") / APP_NAME


def save_dir() -> Path:
    """The folder that holds ``party.json`` and ``roster.json``."""
    override = os.environ.get(SAVE_DIR_ENV)
    if override:
        return Path(override)
    return user_data_dir()


def party_save_path() -> Path:
    """The one save slot (LairWare's single game; user ruling 2026-11-25)."""
    return save_dir() / PARTY_FILE


def roster_save_path() -> Path:
    """The roster file (LairWare's 20 roster records, PutRoster)."""
    return save_dir() / ROSTER_FILE


def migrate_legacy_saves(legacy: Path = LEGACY_SAVE_DIR) -> list[Path]:
    """Copy a source checkout's old ``saves/`` files to the new folder once.

    Copies, never moves: the old files stay where they were. Nothing is
    copied over a file that already exists in the new folder, and nothing
    happens while ``PY_EXODUS_SAVE_DIR`` points somewhere of its own.
    Returns the files copied.
    """
    if os.environ.get(SAVE_DIR_ENV):
        return []
    target = save_dir()
    copied: list[Path] = []
    if not legacy.is_dir() or legacy.resolve() == target.resolve():
        return copied
    for name in (PARTY_FILE, ROSTER_FILE):
        src, dst = legacy / name, target / name
        if src.is_file() and not dst.exists():
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(dst)
    return copied
