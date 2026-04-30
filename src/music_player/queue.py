"""Persistent play queue backed by ~/.music-player/queue.json.

Tracks are stored as plain dicts with Subsonic fields:
  id, title, artist, album, duration (seconds).

stream_url is NOT persisted — it's rebuilt fresh on each play via SubsonicClient.
"""

import json
from pathlib import Path

from src.music_player.logging import get_logger

logger = get_logger(__name__)

_QUEUE_FILE = Path.home() / ".music-player" / "queue.json"


class PlayQueue:
    def __init__(self) -> None:
        self.tracks: list[dict] = []
        self.current_index: int = -1
        self._load()

    # ── persistence ───────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if _QUEUE_FILE.exists():
                data = json.loads(_QUEUE_FILE.read_text())
                self.tracks = data.get("tracks", [])
                self.current_index = data.get("current_index", -1)
                logger.info(f"Queue loaded: {len(self.tracks)} tracks, pos={self.current_index}")
        except Exception as exc:
            logger.warning(f"Could not load queue: {exc}")

    def _save(self) -> None:
        try:
            _QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _QUEUE_FILE.write_text(
                json.dumps({"tracks": self.tracks, "current_index": self.current_index}, indent=2)
            )
        except Exception as exc:
            logger.warning(f"Could not save queue: {exc}")

    # ── mutation ──────────────────────────────────────────────────────

    def set_queue(self, tracks: list[dict], start: int = 0) -> None:
        """Replace queue and set current position."""
        self.tracks = [_strip(t) for t in tracks]
        self.current_index = max(0, min(start, len(tracks) - 1)) if tracks else -1
        self._save()

    def add_track(self, track: dict) -> None:
        """Append one track to the end of the queue."""
        self.tracks.append(_strip(track))
        if self.current_index < 0:
            self.current_index = 0
        self._save()

    def add_tracks(self, tracks: list[dict]) -> None:
        for t in tracks:
            self.tracks.append(_strip(t))
        if self.current_index < 0 and self.tracks:
            self.current_index = 0
        self._save()

    def remove(self, index: int) -> None:
        if 0 <= index < len(self.tracks):
            self.tracks.pop(index)
            if index < self.current_index:
                self.current_index -= 1
            elif index == self.current_index:
                self.current_index = min(self.current_index, len(self.tracks) - 1)
            self._save()

    def clear(self) -> None:
        self.tracks = []
        self.current_index = -1
        self._save()

    # ── navigation ────────────────────────────────────────────────────

    def current(self) -> dict | None:
        if 0 <= self.current_index < len(self.tracks):
            return self.tracks[self.current_index]
        return None

    def advance(self) -> dict | None:
        """Move to next track, return it or None if at end."""
        if self.current_index + 1 < len(self.tracks):
            self.current_index += 1
            self._save()
            return self.current()
        return None

    def go_back(self) -> dict | None:
        """Move to previous track, return it or None if at start."""
        if self.current_index > 0:
            self.current_index -= 1
            self._save()
            return self.current()
        return None

    def __len__(self) -> int:
        return len(self.tracks)


def _strip(t: dict) -> dict:
    """Keep only the fields we need — no stream_url (rebuilt fresh each play)."""
    return {k: t[k] for k in ("id", "title", "artist", "album", "duration", "coverArt", "genre") if k in t}


# ── module-level singleton ────────────────────────────────────────────

_queue: PlayQueue | None = None


def get_queue() -> PlayQueue:
    global _queue
    if _queue is None:
        _queue = PlayQueue()
    return _queue
