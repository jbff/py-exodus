"""Music invariant tests: only ONE music track may play at a time.

Regression coverage for the victory-fanfare overlap bug (2026-11-10):
CombatScreen played the music-class Fanfare.ogg through play_sfx (a
mixer.Sound on a mixer channel), so it stacked on top of the looping
mixer.music combat theme — and stacked again on every victory. The
invariant is enforced at the audio layer (AudioManager.play_music owns the
single music stream; play_sfx never plays a music-class track) and by a
source scan so new call sites cannot reintroduce channel-based music.
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.audio import AudioManager, MUSIC_TRACKS
from py_exodus.constants import Profession, Race
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.combat.arena import Action
from py_exodus.screens.combat_screen import CombatScreen
from py_exodus.state_machine import StateMachine


@pytest.fixture(scope="module")
def pygame_setup():
    pygame.init()
    if not pygame.font.get_init():
        pygame.font.init()
    yield
    pygame.quit()


@pytest.fixture
def mock_mixer():
    """Mock pygame.mixer for headless environments lacking SDL_mixer."""
    m = MagicMock()
    m.get_init.return_value = True
    m.music = MagicMock()
    m.music.get_busy.return_value = False
    m.Sound = MagicMock()
    old_mixer = getattr(pygame, "mixer", None)
    setattr(pygame, "mixer", m)
    try:
        yield m
    finally:
        if old_mixer is not None:
            setattr(pygame, "mixer", old_mixer)


@pytest.fixture
def asset_mgr():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


@pytest.fixture
def sample_party():
    """A small party for CombatScreen construction."""
    party = Party()
    party.add_member(PartyMember(Character("Hero", "M", Race.HUMAN, Profession.PALADIN, hp=100)))
    party.add_member(PartyMember(Character("Mage", "M", Race.ELF, Profession.WIZARD, hp=100)))
    return party


def _music_calls(mock_mixer, name: str) -> list:
    """Ordered list of mock_mixer.method_calls entries for music.<name>."""
    return [c for c in mock_mixer.method_calls if c[0] == f"music.{name}"]


def test_play_music_stops_previous_track(pygame_setup, mock_mixer):
    """Switching tracks must stop the old stream before starting the new one."""
    am = AudioManager(sound_dir="src/main/resources/assets/sound", enabled=True)

    assert am.play_music("combat") is True
    assert am.play_music("wander") is True

    # Stop-before-start: a stop() precedes the final play()
    stop_index = [i for i, c in enumerate(mock_mixer.method_calls)
                  if c[0] == "music.stop"]
    play_index = [i for i, c in enumerate(mock_mixer.method_calls)
                  if c[0] == "music.play"]
    assert stop_index and play_index
    assert max(stop_index) < max(play_index), (
        "music.stop() must be called before starting the replacement track"
    )


def test_play_music_same_track_does_not_restart(pygame_setup, mock_mixer):
    """Re-asserting the already-playing track must not restart it."""
    am = AudioManager(sound_dir="src/main/resources/assets/sound", enabled=True)

    assert am.play_music("wander") is True
    stops_before = len(_music_calls(mock_mixer, "stop"))
    assert len(_music_calls(mock_mixer, "play")) == 1
    mock_mixer.music.get_busy.return_value = True
    assert am.play_music("wander") is True

    assert len(_music_calls(mock_mixer, "stop")) == stops_before, (
        "same-track re-assertion must not stop/restart the stream"
    )
    assert len(_music_calls(mock_mixer, "play")) == 1


def test_play_sfx_never_plays_music_class_track(pygame_setup, mock_mixer):
    """Music-class tracks requested via the SFX path must route to play_music."""
    am = AudioManager(sound_dir="src/main/resources/assets/sound", enabled=True)

    assert am.play_sfx("Fanfare") is True

    assert am.current_track is not None and "Fanfare" in am.current_track
    assert _music_calls(mock_mixer, "play"), "fanfare must go through the music stream"
    assert mock_mixer.Sound.call_count == 0, (
        "music-class tracks must never be played as mixer.Sound channels"
    )


def test_sfx_still_play_over_music(pygame_setup, mock_mixer):
    """SFX via mixer.Sound channels may overlap the running music stream."""
    am = AudioManager(sound_dir="src/main/resources/assets/sound", enabled=True)

    assert am.play_music("combat") is True
    layer = ("load", "stop", "play", "set_volume")
    counts_before = {n: len(_music_calls(mock_mixer, n)) for n in layer}

    sound = MagicMock()
    mock_mixer.Sound.return_value = sound
    assert am.play_sfx("walk_normal") is True
    sound.play.assert_called_once()

    # Music stream is untouched by the SFX call
    for n in layer:
        assert len(_music_calls(mock_mixer, n)) == counts_before[n]


def test_victory_fanfare_routes_through_music_stream(
    pygame_setup, mock_mixer, asset_mgr, sample_party
):
    """Combat victory plays the fanfare as the single music track, not an SFX.

    The user's overlap scenario: combat music (mixer.music) is looping while
    the victory fanfare fired through a mixer.Sound channel. Real flow:
    CombatScreen.on_enter -> play_music("combat"), then the victory branch
    in _execute_action.
    """
    from py_exodus.world.loader import MapLoader

    loader = MapLoader(asset_mgr)
    c_map = loader.load_conflict_map("cnflct_g.json")

    sm = StateMachine(asset_mgr)
    audio = AudioManager(sound_dir="src/main/resources/assets/sound", enabled=True)
    combat = CombatScreen(
        party=sample_party,
        combat_map=c_map,
        creature_tile="orc",
        asset_mgr=asset_mgr,
        audio=audio,
        monster_count=1,
        manager=sm,
    )
    sm.push_screen(combat)  # StateMachine.push_screen invokes on_enter
    assert combat.arena is not None

    # A real combat turn executes in the arena; for this test we only need
    # the victory branch of _execute_action, so stub the arena turn and
    # force the finished/victory state the branch reads.
    res_stub = MagicMock()
    res_stub.attack_res = None
    res_stub.spell_res = None
    combat.arena.execute_turn = MagicMock(return_value=res_stub)
    combat.arena.is_finished = True
    combat.arena.is_victory = True

    combat._execute_action(Action.pass_turn())

    # on_enter played "combat", victory then swapped in "fanfare" on the
    # single music stream — never a Sound channel.
    assert audio.current_track is not None and "Fanfare" in audio.current_track
    play_index = [i for i, c in enumerate(mock_mixer.method_calls)
                  if c[0] == "music.play"]
    stop_index = [i for i, c in enumerate(mock_mixer.method_calls)
                  if c[0] == "music.stop"]
    assert len(play_index) == 2, (
        "combat theme + fanfare = exactly two music stream starts"
    )
    # Victory sting plays ONCE (user ruling): pygame loops counts REPEATS,
    # so loop-once is play(loops=0). The on_enter combat theme keeps the
    # default infinite loop; the sting call must not.
    sting_call = mock_mixer.method_calls[max(play_index)]
    assert sting_call.args == (0,), (
        f"victory sting must be the loop-once idiom play(0), got {sting_call!r}"
    )
    assert play_index[0] != max(play_index) and (
        mock_mixer.method_calls[play_index[0]].args == (-1,)
    ), "combat theme stays looping (default)"
    assert stop_index and max(stop_index) < max(play_index), (
        "fanfare must stop the combat theme before starting"
    )
    assert mock_mixer.Sound.call_count == 0, (
        "no track may fire through a mixer.Sound channel"
    )


def test_source_scan_no_music_tracks_through_sfx():
    """Source scan: play_sfx must never be called with a music-class name."""
    callers = [p for p in Path("py_exodus").rglob("*.py")
               if "__pycache__" not in p.parts]
    pattern = re.compile(r"""play_sfx\(\s*["']([^"']+)["']""")
    offenders: list[str] = []
    for path in callers:
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            name = match.group(1).strip().lower()
            if name in MUSIC_TRACKS:
                offenders.append(f"{path}: play_sfx('{match.group(1)}')")
    assert offenders == [], (
        "music-class tracks must go through play_music, not play_sfx: "
        + "; ".join(offenders)
    )
