# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build specification for Music Player.

Outputs
-------
--onefile  (default via build.bat):
    dist\music_player.exe   — single large executable, slower first launch

--onedir   (fast startup, folder distribution):
    dist\music_player\      — folder; zip it up to share

Usage
-----
    # Install PyInstaller first (once):
    uv add --dev pyinstaller

    # Build single .exe:
    scripts\\build.bat

    # Build folder instead (faster startup):
    uv run pyinstaller music_player.spec --onedir

After building, copy your .env file into the output directory so the app
can find your Subsonic credentials.
"""

import sys
from pathlib import Path

root = Path(".").resolve()

# ── collect native DLLs ───────────────────────────────────────────────────────

mpv_dlls      = [(str(p), "lib/mpv")      for p in (root / "lib" / "mpv").glob("*.dll")]
projectm_dlls = [(str(p), "lib/projectm") for p in (root / "lib" / "projectm").glob("*.dll")]

# ── collect data files ────────────────────────────────────────────────────────

datas = [
    (str(root / "lib" / "projectm" / "presets"), "lib/projectm/presets"),
]
tex = root / "lib" / "projectm" / "textures"
if tex.is_dir():
    datas.append((str(tex), "lib/projectm/textures"))

env_example = root / ".env.example"
if env_example.exists():
    datas.append((str(env_example), "."))

# ── analysis ──────────────────────────────────────────────────────────────────

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=mpv_dlls + projectm_dlls,
    datas=datas,
    hiddenimports=[
        # PyQt6 OpenGL — not always auto-detected
        "PyQt6.QtOpenGL",
        "PyQt6.QtOpenGLWidgets",
        "PyQt6.sip",
        # audio / visualizer
        "mpv",
        "sounddevice",
        "sounddevice._sounddevice",
        "numpy",
        # networking / config
        "httpx",
        "dotenv",
        "python_dotenv",
    ],
    hookspath=[],
    hooksconfig={
        "PyQt6": {
            "qt_plugins": [
                "platforms",
                "styles",
                "imageformats",
                "iconengines",
            ],
        },
    },
    runtime_hooks=[],
    excludes=[
        "ruff",          # linter — not needed at runtime
        "pytest",
        "tkinter",
        "matplotlib",
        "IPython",
        "jupyter",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

# ── determine build mode ──────────────────────────────────────────────────────
# Default: --onefile.  Pass --onedir on the command line to get a folder build.

_onedir = "--onedir" in sys.argv or "-D" in sys.argv

if _onedir:
    # ── folder build (fast startup) ───────────────────────────────────────────
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="music_player",
        debug=False,
        strip=False,
        upx=True,
        console=False,
        icon=str(root / "icon.ico") if (root / "icon.ico").exists() else None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name="music_player",
    )
else:
    # ── single-file build (default) ───────────────────────────────────────────
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        name="music_player",
        debug=False,
        strip=False,
        upx=True,
        console=False,
        icon=str(root / "icon.ico") if (root / "icon.ico").exists() else None,
    )
