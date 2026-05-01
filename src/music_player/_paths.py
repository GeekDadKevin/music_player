"""Resolve the application root directory in source and PyInstaller modes.

Usage
-----
    from src.music_player._paths import app_root
    dll_path = app_root() / "lib" / "mpv" / "libmpv-2.dll"

How it works
------------
Source run (uv run main.py):
    Returns Path(__file__).parents[2] — i.e. three levels up from
    src/music_player/_paths.py  →  project root.

PyInstaller --onefile:
    All files are extracted to sys._MEIPASS at startup. lib/ is there too.

PyInstaller --onedir:
    Files sit next to the .exe. sys._MEIPASS is absent; use the exe dir.
"""

import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        return Path(meipass) if meipass else Path(sys.executable).parent
    # src/music_player/_paths.py → src/music_player/ → src/ → project root
    return Path(__file__).parents[2]
