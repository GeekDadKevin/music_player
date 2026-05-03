"""Playlist file import — parse M3U/JSPF then fuzzy-match against Subsonic."""

import json
import os
from difflib import SequenceMatcher

import requests as _requests
from PyQt6.QtCore import QThread, pyqtSignal

from src.music_player.logging import get_logger
from src.music_player.repository.subsonic_client import SubsonicClient

logger = get_logger(__name__)

_MATCH_THRESHOLD = 0.55   # minimum score to consider a song matched


# ── file parsers ──────────────────────────────────────────────────────

def parse_m3u(content: str) -> list[dict]:
    """Parse M3U/M3U8 content into a list of raw track dicts.

    Extracts title and artist from #EXTINF lines.  Falls back to parsing
    the filename if no EXTINF is present.  Keys: title, artist, duration, path.
    """
    tracks: list[dict] = []
    current: dict | None = None

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("#EXTINF:"):
            rest = line[8:]
            comma = rest.find(",")
            if comma >= 0:
                display = rest[comma + 1:].strip()
                if " - " in display:
                    artist, title = display.split(" - ", 1)
                else:
                    artist, title = "", display
                try:
                    duration = int(rest[:comma])
                except ValueError:
                    duration = 0
                current = {"title": title.strip(), "artist": artist.strip(), "duration": duration}
            continue

        if line.startswith("#"):
            continue

        # File path / URL
        path = line
        if current:
            current["path"] = path
            tracks.append(current)
            current = None
        else:
            # No EXTINF — extract from filename
            name = os.path.splitext(os.path.basename(path.replace("\\", "/")))[0]
            if " - " in name:
                artist, title = name.split(" - ", 1)
            else:
                artist, title = "", name
            tracks.append({"title": title.strip(), "artist": artist.strip(), "duration": 0, "path": path})

    return tracks


def parse_jspf(content: str) -> list[dict]:
    """Parse JSPF (JSON playlist format) content.

    Keys in returned dicts: title, artist, duration (seconds), path.
    """
    data = json.loads(content)
    pl = data.get("playlist", data)
    tracks: list[dict] = []
    for t in pl.get("track", []):
        loc = t.get("location", "")
        if isinstance(loc, list):
            loc = loc[0] if loc else ""
        tracks.append({
            "title":    t.get("title", ""),
            "artist":   t.get("creator", ""),
            "duration": int(t.get("duration", 0)) // 1000,
            "path":     loc,
        })
    return tracks


# ── matching ──────────────────────────────────────────────────────────

def _score(title1: str, artist1: str, title2: str, artist2: str) -> float:
    t1, t2 = title1.lower().strip(), title2.lower().strip()
    a1, a2 = artist1.lower().strip(), artist2.lower().strip()
    title_sim = SequenceMatcher(None, t1, t2).ratio()
    if a1 and a2:
        artist_sim = SequenceMatcher(None, a1, a2).ratio()
        return title_sim * 0.65 + artist_sim * 0.35
    return title_sim * 0.8


def find_match(client: SubsonicClient, title: str, artist: str) -> dict | None:
    """Search Subsonic and return the best-matching song dict, or None.

    Always prefers a locally-available song over an ext-deezer virtual entry
    when both score above the threshold — Navidrome can hold both versions and
    the ext-deezer one would otherwise score higher simply by appearing first.
    """
    if not title:
        return None

    candidates: list[dict] = []
    for query in (f"{title} {artist}".strip(), title):
        candidates = client.search(query, song_count=15)
        if candidates:
            break

    best_local, best_local_score = None, 0.0
    best_ext,   best_ext_score   = None, 0.0
    for song in candidates:
        s = _score(title, artist, song.get("title", ""), song.get("artist", ""))
        if song.get("id", "").startswith("ext-"):
            if s > best_ext_score:
                best_ext_score, best_ext = s, song
        else:
            if s > best_local_score:
                best_local_score, best_local = s, song

    if best_local_score >= _MATCH_THRESHOLD:
        return best_local
    if best_ext_score >= _MATCH_THRESHOLD:
        return best_ext
    return None


# ── worker ────────────────────────────────────────────────────────────

class PlaylistImportWorker(QThread):
    """Parse a playlist file and fuzzy-match each track against Subsonic.

    Emits one signal per track as matching progresses so the UI can update
    row by row, then emits finished() with the playlist title.

    Signals:
        progress(done, total, message)     — how many tracks processed so far
        track_result(index, matched, raw)  — matched is dict|None; raw is parsed dict
        finished(playlist_title)
        error(str)
    """

    progress     = pyqtSignal(int, int, str)
    track_result = pyqtSignal(int, object, dict)   # index, dict|None, raw_dict
    finished     = pyqtSignal(str)
    error        = pyqtSignal(str)

    def __init__(self, filepath: str, parent=None) -> None:
        super().__init__(parent)
        self._filepath = filepath

    def run(self) -> None:
        try:
            with open(self._filepath, encoding="utf-8", errors="replace") as fh:
                content = fh.read()

            ext = os.path.splitext(self._filepath)[1].lower()
            if ext in (".m3u", ".m3u8"):
                raw_tracks = parse_m3u(content)
            elif ext == ".jspf":
                raw_tracks = parse_jspf(content)
            else:
                self.error.emit(f"Unsupported format: {ext}")
                return

            title = os.path.splitext(os.path.basename(self._filepath))[0]
            client = SubsonicClient()
            total = len(raw_tracks)

            for i, raw in enumerate(raw_tracks):
                self.progress.emit(i, total, f"Matching {i + 1}/{total}: {raw.get('title', '?')}")
                matched = find_match(client, raw.get("title", ""), raw.get("artist", ""))
                self.track_result.emit(i, matched, raw)

            self.finished.emit(title)

        except Exception as exc:
            logger.error(f"PlaylistImportWorker: {exc}")
            self.error.emit(str(exc))
