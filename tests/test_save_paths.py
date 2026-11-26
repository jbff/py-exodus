"""Saves live in the per-user data folder (2026-11-26), so a packaged app or
a read-only install folder can still save. Tests pin it to ./saves."""
import sys
from pathlib import Path

from py_exodus import paths


def test_tests_never_touch_the_players_folder():
    assert paths.save_dir() == Path("saves")


def test_per_user_folder_by_system(monkeypatch, tmp_path):
    monkeypatch.delenv(paths.SAVE_DIR_ENV)
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert paths.save_dir() == tmp_path / "Roaming" / "py-exodus"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert paths.save_dir() == tmp_path / "Library" / "Application Support" / "py-exodus"
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert paths.save_dir() == tmp_path / ".local" / "share" / "py-exodus"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert paths.party_save_path() == tmp_path / "xdg" / "py-exodus" / "party.json"
    assert paths.roster_save_path() == tmp_path / "xdg" / "py-exodus" / "roster.json"


def test_old_saves_are_copied_once_and_never_overwritten(monkeypatch, tmp_path):
    monkeypatch.delenv(paths.SAVE_DIR_ENV)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    legacy = tmp_path / "old" / "saves"
    legacy.mkdir(parents=True)
    (legacy / "party.json").write_text("old party")
    (legacy / "roster.json").write_text("old roster")
    new = tmp_path / "xdg" / "py-exodus"

    copied = paths.migrate_legacy_saves(legacy)
    assert sorted(p.name for p in copied) == ["party.json", "roster.json"]
    assert (new / "party.json").read_text() == "old party"
    assert (legacy / "party.json").exists()  # copied, not moved

    (new / "party.json").write_text("newer game")
    assert paths.migrate_legacy_saves(legacy) == []
    assert (new / "party.json").read_text() == "newer game"


def test_no_migration_while_the_folder_is_overridden(tmp_path):
    legacy = tmp_path / "saves"
    legacy.mkdir()
    (legacy / "party.json").write_text("x")
    assert paths.migrate_legacy_saves(legacy) == []
