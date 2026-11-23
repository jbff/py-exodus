"""'--tiles list' (user 2026-11-23): the default set first, marked."""
import pytest

from py_exodus.__main__ import main
from py_exodus.assets import DEFAULT_TILESET, LAIRWARE_TILESETS, tileset_listing


def test_listing_puts_the_default_first_and_marks_it():
    names = tileset_listing().split(", ")
    assert names[0] == f"{DEFAULT_TILESET} [default]" == "ega [default]"
    assert sorted(n.split()[0] for n in names) == sorted(LAIRWARE_TILESETS)
    assert sum("[default]" in n for n in names) == 1


def test_tiles_list_prints_it(capsys):
    with pytest.raises(SystemExit) as done:
        main(["--tiles", "list"])
    assert done.value.code == 0
    assert capsys.readouterr().out.strip() == "Tile sets: " + tileset_listing()
