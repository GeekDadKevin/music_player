<<<<<<< HEAD
"""SearchAndPlayWorker — resolve a _missing track to a playable Subsonic song.

Resolution order:
  1. Subsonic search (find_match) — returns the best local or ext-deezer match.
  2. Deezer public API fallback — constructs the ext-deezer-song-{id} reference
     that Navidrome/Octofiesta exposes for catalog tracks it hasn't downloaded yet.

IMPORTANT — there is NO separate "download trigger" request here.
The stream request that mpv opens when the caller plays the returned track is
the only signal Navidrome/Octofiesta needs to start a download.  Any extra HTTP
request to the stream endpoint (HEAD or GET) interrupts an in-progress download
and must never be added back.
=======
"""SearchAndPlayWorker — resolve a missing track to something Navidrome can stream.

Resolution order:
  1. Subsonic search (find_match) — returns a match only when the primary
     artist is similar enough to the target (avoids wrong-artist false positives).
  2. Deezer public API fallback — if Subsonic has no usable match, we look up
     the Deezer track ID and construct the ext-deezer-song-{id} reference that
     Navidrome exposes.

In both cases the worker emits ``found`` with the best available track dict —
local file or ext-deezer proxy.  Playback is started by the caller; the
stream request that mpv opens is the only signal Navidrome/Octofiesta needs
to begin a download.  No separate "trigger" request is sent here.
>>>>>>> afc523b69e5e46e1c85ac366e6b1e0f2c49b543c
"""

import re
from difflib import SequenceMatcher

from PyQt6.QtCore import QThread, pyqtSignal

from src.music_player.logging import get_logger
from src.music_player.repository.subsonic_client import SubsonicClient

logger = get_logger(__name__)

_FT_RE = re.compile(r'\s+(?:ft\.?|feat\.?|featuring|with)\s+.*', re.IGNORECASE)


def _primary_artist(name: str) -> str:
    """Strip feature credits and return the primary artist name, lower-cased."""
    return _FT_RE.sub("", name).strip().lower()


def _artist_ok(matched: str, target: str) -> bool:
    if not target or not matched:
        return True
    return SequenceMatcher(None, _primary_artist(matched), _primary_artist(target)).ratio() >= 0.6


class SearchAndPlayWorker(QThread):
    """Resolve a _missing track to the best available playable dict.

<<<<<<< HEAD
    Emits ``found`` with the track dict — either a locally-indexed song or an
    ext-deezer proxy entry.  The caller starts playback; mpv's stream request
    to Navidrome is the download trigger for Octofiesta, nothing else.

    ``not_found`` is emitted when the track cannot be located in either
    Subsonic or Deezer.
    """

    found     = pyqtSignal(dict)   # best match (local file or ext-deezer proxy)
    not_found = pyqtSignal()       # not found in Subsonic or Deezer
=======
    ``not_found`` is emitted when neither Subsonic nor Deezer can locate the
    track.  The caller is responsible for starting playback via bridge.play_track;
    that stream request is what Navidrome/Octofiesta uses to trigger a download.
    """

    found     = pyqtSignal(dict)   # track is playable — local file or ext-deezer proxy
    not_found = pyqtSignal()       # not found anywhere
>>>>>>> afc523b69e5e46e1c85ac366e6b1e0f2c49b543c

    def __init__(self, title: str, artist: str, parent=None) -> None:
        super().__init__(parent)
        self._title  = title
        self._artist = artist

    def run(self) -> None:
        try:
            from src.music_player.ui.workers.playlist_import import find_match
            client = SubsonicClient()
            match  = find_match(client, self._title, self._artist)
            if match and _artist_ok(match.get("artist", ""), self._artist):
                logger.info(
<<<<<<< HEAD
                    f"Resolved {self._title!r} → {match['id']}"
=======
                    f"Resolved {self._title!r} → id={match['id']}"
>>>>>>> afc523b69e5e46e1c85ac366e6b1e0f2c49b543c
                    + (" (ext-deezer proxy)" if match["id"].startswith("ext-") else "")
                )
                self.found.emit(match)
                return

            # Subsonic had no usable match — try Deezer for the ext-deezer reference.
            deezer = self._deezer_lookup()
            if deezer:
<<<<<<< HEAD
                logger.info(f"Resolved via Deezer: {self._title!r} → {deezer['id']}")
=======
                logger.info(f"Resolved via Deezer: {self._title!r} → id={deezer['id']}")
>>>>>>> afc523b69e5e46e1c85ac366e6b1e0f2c49b543c
                self.found.emit(deezer)
            else:
                logger.info(f"Track not found anywhere: {self._title!r}")
                self.not_found.emit()
        except Exception as exc:
            logger.error(f"SearchAndPlayWorker error: {exc}")
            self.not_found.emit()

    def _deezer_lookup(self) -> dict | None:
        """Search Deezer's public API and return a synthetic ext-deezer dict."""
        try:
            import requests
            resp = requests.get(
                "https://api.deezer.com/search",
                params={"q": f"{self._title} {self._artist}", "limit": 10},
                timeout=8,
            )
            resp.raise_for_status()
            target_title  = self._title.lower().strip()
            target_artist = _primary_artist(self._artist)
            for item in resp.json().get("data", []):
                t_sim = SequenceMatcher(
                    None, item.get("title", "").lower(), target_title
                ).ratio()
                a_sim = SequenceMatcher(
                    None,
                    _primary_artist(item.get("artist", {}).get("name", "")),
                    target_artist,
                ).ratio()
                if t_sim >= 0.85 and a_sim >= 0.7:
                    return {
                        "id":       f"ext-deezer-song-{item['id']}",
                        "title":    item.get("title", self._title),
                        "artist":   item.get("artist", {}).get("name", self._artist),
                        "album":    item.get("album", {}).get("title", ""),
                        "duration": item.get("duration", 0),
                        "coverArt": f"ext-deezer-song-{item['id']}",
                    }
        except Exception as exc:
            logger.debug(f"Deezer lookup failed for {self._title!r}: {exc}")
        return None
