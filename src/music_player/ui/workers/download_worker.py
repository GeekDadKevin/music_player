"""SearchAndPlayWorker — resolve a missing track so Octofiesta can download it.

Resolution order:
  1. Subsonic search (find_match) — returns a match only when the primary
     artist is similar enough to the target (avoids wrong-artist false positives).
  2. Deezer public API fallback — if Subsonic has no usable match, we look up
     the Deezer track ID and construct the ext-deezer-song-{id} reference that
     Navidrome exposes.  Playing that stream URL triggers the Octofiesta download
     even when Navidrome's ext-deezer metadata is wrong or missing.
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
    """Resolve a missing track to a playable dict and emit ``found``.

    ``not_found`` is emitted when both Subsonic and Deezer searches come up
    empty, so the caller can retry later (e.g. while Octofiesta is downloading).
    """

    found     = pyqtSignal(dict)
    not_found = pyqtSignal()

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
                if match.get("id", "").startswith("ext-"):
                    # Track is in the Navidrome catalog but not downloaded yet.
                    # Trigger the download via a HEAD request, then signal not_found
                    # so the caller retries — once Navidrome indexes the local file
                    # find_match will return a non-ext ID and we can actually play it.
                    self._trigger_download(client, match["id"])
                    logger.info(
                        f"Triggered download for ext track {self._title!r} "
                        f"({match['id']}) — will retry"
                    )
                    self.not_found.emit()
                    return
                logger.info(f"Resolved via Subsonic: {self._title!r} → id={match['id']}")
                self.found.emit(match)
                return

            # Subsonic had no match or returned a wrong-artist song.
            # Try Deezer to get the canonical ext-deezer-song-{id} reference.
            deezer = self._deezer_lookup()
            if deezer:
                # Trigger the download immediately; the retry loop will wait
                # for Navidrome to index the local file before playing.
                self._trigger_download(client, deezer["id"])
                logger.info(
                    f"Triggered Deezer download for {self._title!r} "
                    f"({deezer['id']}) — will retry"
                )
                self.not_found.emit()
            else:
                logger.info(f"Missing track not available anywhere: {self._title!r}")
                self.not_found.emit()
        except Exception as exc:
            logger.error(f"SearchAndPlayWorker error: {exc}")
            self.not_found.emit()

    def _trigger_download(self, client: SubsonicClient, song_id: str) -> None:
        """Fire a HEAD request to the stream URL — tells Navidrome/Octofiesta to download."""
        try:
            import requests as _req
            url = client.get_stream_url(song_id)
            _req.head(url, timeout=4)
        except Exception:
            pass

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
