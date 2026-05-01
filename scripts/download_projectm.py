"""
Download pre-built projectM 4.1.3 Windows binaries and extract them into
lib/projectm/ so the music player can load libprojectM-4.dll from the
project directory without any system-wide installation.

Source: frontend-sdl2 pre-release (kblaschke/frontend-sdl2)
  https://github.com/kblaschke/frontend-sdl2/releases/tag/2.0-windows-pre3

Run once:
  uv run python scripts/download_projectm.py

What gets extracted into lib/projectm/:
  - projectM-4.dll          (main library, loaded by the app via ctypes)
  - presets/                (*.milk preset files)
  - any other projectM-prefixed DLLs present in the zip

SDL2.dll and other frontend-only DLLs are intentionally skipped; the app
uses Qt for windowing and does not need them.
"""

import io
import sys
import zipfile
from pathlib import Path

import httpx

# ── configuration ────────────────────────────────────────────────────────

_ZIP_URL = (
    "https://github.com/kblaschke/frontend-sdl2/releases/download/"
    "2.0-windows-pre3/projectMSDL-Windows-x64-2.0-pre3.zip"
)

_PROJECT_ROOT = Path(__file__).parents[1]
_DEST = _PROJECT_ROOT / "lib" / "projectm"

# DLLs to skip — SDL2 is the window/input layer for the standalone frontend
# and is not needed by libprojectM itself; MSVC CRT DLLs are system-provided.
_SKIP_DLLS = {
    "SDL2.dll",
    "projectMSDL.exe",
}

# ── helpers ───────────────────────────────────────────────────────────────

def _download(url: str) -> bytes:
    print(f"Downloading {url}")
    chunks: list[bytes] = []
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        received = 0
        for chunk in r.iter_bytes(chunk_size=65536):
            chunks.append(chunk)
            received += len(chunk)
            if total:
                pct = received / total * 100
                bar = "#" * int(pct / 2)
                print(f"\r  [{bar:<50}] {pct:5.1f}%  {received // 1024 // 1024} MB", end="", flush=True)
    print()
    return b"".join(chunks)


def _want(name: str) -> bool:
    """Return True for files we want to extract."""
    basename = Path(name).name
    low = basename.lower()
    # Skip the SDL2 frontend EXE and its window-manager DLL; keep everything else.
    if basename in _SKIP_DLLS or low in {s.lower() for s in _SKIP_DLLS}:
        return False
    if low.endswith(".dll"):
        return True
    # Presets
    if low.endswith(".milk"):
        return True
    # Textures (JPEG images used by preset shaders via sampler_* uniforms)
    if low.endswith((".jpg", ".jpeg", ".png")):
        return True
    return False


def _dest_path(zip_name: str) -> Path:
    """Map a zip entry path to the destination path inside lib/projectm/."""
    p = Path(zip_name)
    parts = p.parts
    lower_parts = [pt.lower() for pt in parts]

    if p.suffix.lower() == ".dll":
        return _DEST / p.name

    # .milk files — keep everything from the 'presets' segment onwards
    if p.suffix.lower() == ".milk":
        try:
            idx = next(i for i, pt in enumerate(lower_parts) if "preset" in pt)
            rel = Path(*parts[idx:])
        except StopIteration:
            rel = Path("presets") / p.name
        return _DEST / rel

    # Texture images — keep everything from the 'texture' segment onwards
    if p.suffix.lower() in (".jpg", ".jpeg", ".png"):
        try:
            idx = next(i for i, pt in enumerate(lower_parts) if "texture" in pt)
            rel = Path(*parts[idx:])
        except StopIteration:
            rel = Path("textures") / p.name
        return _DEST / rel

    return _DEST / p.name


# ── main ─────────────────────────────────────────────────────────────────

def main() -> None:
    _DEST.mkdir(parents=True, exist_ok=True)

    # Check if already done — all runtime DLLs present means no re-download needed
    existing_dlls = list(_DEST.glob("*.dll"))
    if len(existing_dlls) >= 10:   # expect ~15 DLLs total
        print(f"{len(existing_dlls)} DLLs already present in {_DEST}")
        print("Delete lib/projectm/*.dll and re-run to re-download.")
        return

    data = _download(_ZIP_URL)
    zf   = zipfile.ZipFile(io.BytesIO(data))

    print(f"\nExtracting to {_DEST} ...")
    extracted: list[str] = []
    skipped:   list[str] = []

    for entry in zf.infolist():
        if entry.is_dir():
            continue
        if not _want(entry.filename):
            skipped.append(entry.filename)
            continue

        dest = _dest_path(entry.filename)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(zf.read(entry.filename))
        extracted.append(str(dest.relative_to(_PROJECT_ROOT)))

    print(f"\nExtracted {len(extracted)} file(s):")
    for f in sorted(extracted):
        print(f"  {f}")

    dll = _DEST / "projectM-4.dll"
    if not dll.exists():
        print("\nWARNING: projectM-4.dll was not found in the zip.")
        print("Files in zip:")
        for e in zf.infolist():
            if not e.is_dir():
                print(f"  {e.filename}")
        sys.exit(1)

    presets = list((_DEST / "presets").rglob("*.milk")) if (_DEST / "presets").exists() else []
    print(f"\nDone.  {len(presets)} presets available.")
    print("Restart the music player to enable MilkDrop.")


if __name__ == "__main__":
    main()
