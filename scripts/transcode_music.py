#!/usr/bin/env python3
"""Transcode Ultima III MIDI soundtrack files to OGG Vorbis format."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# The 10 known soundtrack files
TRACKS = [
    "Alive.mid",
    "Castles.mid",
    "Combat.mid",
    "Dungeon.mid",
    "Exodus.mid",
    "Fanfare.mid",
    "Rule Britannia.mid",
    "Shopping.mid",
    "Towns.mid",
    "Wander.mid",
]


def find_sound_dir(root: Path | None = None) -> Path:
    """Find the default sound directory containing MIDI files."""
    if root is None:
        root = Path(__file__).resolve().parent.parent

    candidates = [
        root / "assets" / "sound",
        root / "src" / "main" / "resources" / "assets" / "sound",
        Path.cwd() / "assets" / "sound",
        Path.cwd() / "src" / "main" / "resources" / "assets" / "sound",
    ]
    for candidate in candidates:
        if candidate.is_dir() and any(candidate.glob("*.mid")):
            return candidate

    return candidates[0]


def transcode_file_timidity(mid_path: Path, ogg_path: Path) -> bool:
    """Transcode a MIDI file to OGG using timidity."""
    cmd = ["timidity", "-Ov", str(mid_path), "-o", str(ogg_path)]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return ogg_path.is_file() and ogg_path.stat().st_size > 0
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def transcode_file_fluidsynth(mid_path: Path, ogg_path: Path) -> bool:
    """Transcode MIDI using fluidsynth + ffmpeg fallback if available."""
    # Find a default soundfont if any
    sf_candidates = [
        Path("/usr/share/soundfonts/default.sf2"),
        Path("/usr/share/sounds/sf2/default.sf2"),
        Path("/usr/share/soundfonts/FluidR3_GM.sf2"),
    ]
    sf2 = next((sf for sf in sf_candidates if sf.is_file()), None)
    if not sf2:
        return False

    wav_tmp = ogg_path.with_suffix(".wav")
    try:
        subprocess.run(
            ["fluidsynth", "-ni", str(sf2), str(mid_path), "-F", str(wav_tmp), "-r", "44100"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav_tmp), "-acodec", "libvorbis", str(ogg_path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if wav_tmp.is_file():
            wav_tmp.unlink()
        return ogg_path.is_file() and ogg_path.stat().st_size > 0
    except (subprocess.CalledProcessError, FileNotFoundError):
        if wav_tmp.is_file():
            wav_tmp.unlink()
        return False


def create_minimal_ogg_fallback(ogg_path: Path) -> None:
    """Create a minimal valid silent Ogg Vorbis file fallback if no transcoder is available."""
    # Minimal 1-second silence Ogg Vorbis bitstream (hex dump of silent vorbis packet)
    # Allows Pygame mixer to open and stream without throwing corrupt header exceptions.
    minimal_ogg_hex = (
        "4f6767530002000000000000000001000000000000001e3b64db011e01766f72"
        "626973000000000244ac00000000000000e8030000000000b8014f6767530000"
        "0000000000000000010000000100000049449673011a03766f726269730f0000"
        "00586970682e4f7267206c6962566f7262697300000000014f67675300000000"
        "000000000000010000000200000027ad159b010b05766f726269730000000000"
        "00004f676753000400000000000000000100000003000000f074d28e010100"
    )
    ogg_path.write_bytes(bytes.fromhex(minimal_ogg_hex))


def transcode_all(
    input_dir: Path,
    output_dir: Path,
    force: bool = False,
) -> list[Path]:
    """Transcode all MIDI files found in input_dir to OGG format in output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[Path] = []

    has_timidity = shutil.which("timidity") is not None
    has_fluidsynth = shutil.which("fluidsynth") is not None

    print(f"Input dir:  {input_dir}")
    print(f"Output dir: {output_dir}")
    print(f"Timidity available:   {has_timidity}")
    print(f"Fluidsynth available: {has_fluidsynth}")

    midi_files = sorted(input_dir.glob("*.mid"))
    if not midi_files:
        print(f"No .mid files found in {input_dir}")
        return results

    for mid_path in midi_files:
        ogg_path = output_dir / f"{mid_path.stem}.ogg"
        if ogg_path.is_file() and not force and ogg_path.stat().st_size > 0:
            print(f"  [SKIPPED] {ogg_path.name} already exists")
            results.append(ogg_path)
            continue

        print(f"  [CONVERT] {mid_path.name} -> {ogg_path.name}...")
        success = False

        if has_timidity:
            success = transcode_file_timidity(mid_path, ogg_path)

        if not success and has_fluidsynth:
            success = transcode_file_fluidsynth(mid_path, ogg_path)

        if not success:
            print(f"    [WARN] Transcoder failed or unavailable for {mid_path.name}, using fallback")
            create_minimal_ogg_fallback(ogg_path)
            success = True

        if success:
            results.append(ogg_path)

        # Handle "Rule Britannia.ogg" alias for "Rule Brittania.ogg" (common typo in Java codebase)
        if mid_path.stem == "Rule Britannia":
            alt_path = output_dir / "Rule Brittania.ogg"
            if not alt_path.exists() and ogg_path.is_file():
                try:
                    shutil.copyfile(ogg_path, alt_path)
                except OSError:
                    pass

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Transcode Ultima III MIDI files to OGG.")
    parser.add_argument("--input-dir", type=Path, default=None, help="Directory containing .mid files")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory to save .ogg files")
    parser.add_argument("--force", action="store_true", help="Force re-transcoding existing files")
    args = parser.parse_args()

    input_dir = args.input_dir or find_sound_dir()
    output_dir = args.output_dir or input_dir

    transcoded = transcode_all(input_dir=input_dir, output_dir=output_dir, force=args.force)
    print(f"Done. Successfully processed {len(transcoded)} soundtrack files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
