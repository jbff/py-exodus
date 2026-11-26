# PyInstaller spec for the py-exodus desktop builds.
# Build from the repository root:  pyinstaller packaging/py-exodus.spec
# Output: dist/py-exodus/ (Windows, Linux) or dist/py-exodus.app (macOS).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from py_exodus import __version__  # noqa: E402

datas = [(str(ROOT / "assets"), "assets")]
datas += [(str(ROOT / name), ".") for name in ("LICENSE", "THIRD_PARTY_NOTICES.md")]
binaries = []
# PortAudio and libsndfile ship inside these wheels' data packages.
for pkg in ("_sounddevice_data", "_soundfile_data"):
    try:
        datas += collect_data_files(pkg)
        binaries += collect_dynamic_libs(pkg)
    except Exception:
        pass

a = Analysis(
    [str(ROOT / "packaging" / "run_exodus.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["sounddevice", "soundfile"],
    excludes=["tkinter", "pytest", "torch", "triton", "PIL"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="py-exodus",
    console=False,
    icon=str(ROOT / "packaging" / "icon.png"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="py-exodus")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="py-exodus.app",
        icon=str(ROOT / "packaging" / "icon.png"),
        bundle_identifier="io.github.jbff.py-exodus",
        version=__version__,
        info_plist={
            "CFBundleDisplayName": "py-exodus",
            "CFBundleShortVersionString": __version__,
            "NSHighResolutionCapable": True,
        },
    )
