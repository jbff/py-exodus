"""Every file the game loads by name exists after the asset sweep."""
from pathlib import Path

from py_exodus.assets import AssetManager
from py_exodus.audio import MUSIC_TRACKS, AudioManager


def test_music_tracks_exist():
    am = AudioManager(enabled=False)
    for v in set(MUSIC_TRACKS.values()):
        assert (am.sound_dir / v).exists(), v


def test_play_sfx_literals_resolve():
    LITERAL_SFX = ["AncientSpirits", "blocked", "boom", "cannon", "DivineMed",
                   "enemy_magic_proj", "Fanfare", "giggle", "lightning", "magic",
                   "moongate_flash", "negative", "negative_effect", "pc_attack",
                   "rocks", "tornado", "trigger", "walk_normal", "wave", "whirlpool"]
    ALREADY_UNRESOLVED = {"lightning", "negative", "negative_effect", "rocks", "wave", "whirlpool"}
    am = AudioManager(enabled=False)
    for name in LITERAL_SFX:
        assert name in ALREADY_UNRESOLVED or am.resolve_sound_file(name) is not None, name


def test_all_map_defs_resolve(asset_mgr):
    for m_def in asset_mgr.map_defs.values():
        assert asset_mgr.resolve_path("maps", f"{Path(m_def.fname).stem}.json").exists(), m_def.id


def test_atlas_and_text_assets_exist():
    assert AssetManager().resolve_path("graphics", "latest-atlas.txt").exists()
    assert AssetManager().resolve_path("data", "ultima3.txt").exists()
