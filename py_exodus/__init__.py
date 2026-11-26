"""py-exodus: Ultima III: Exodus reimplementation in Python."""

import re

__version__ = "1.0.0b2"


def display_version(version: str = __version__) -> str:
    """The version as players read it: "1.0.0b2" -> "1.0 beta 2",
    "1.0.0" -> "1.0", "1.2.3rc1" -> "1.2.3 rc 1"."""
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?", version)
    if m is None:
        return version
    major, minor, patch, pre, n = m.groups()
    base = f"{major}.{minor}" if patch == "0" else f"{major}.{minor}.{patch}"
    if pre is None:
        return base
    return f"{base} {dict(a='alpha', b='beta', rc='rc')[pre]} {n}"
