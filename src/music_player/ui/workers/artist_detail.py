import concurrent.futures
import re

import requests
from PyQt6.QtCore import QThread, pyqtSignal

from src.music_player.logging import get_logger
from src.music_player.repository.subsonic_client import SubsonicClient

logger = get_logger(__name__)

_MB_HEADERS = {"User-Agent": "music-player/1.0 (kevinloverman@gmail.com)"}


class LoadArtistAlbumsWorker(QThread):
    """Fetches an artist's albums from Subsonic, sorted newest-first."""

    albums_loaded = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, artist_id: str, parent=None) -> None:
        super().__init__(parent)
        self._artist_id = artist_id

    def run(self) -> None:
        try:
            client = SubsonicClient()
            artist = client.get_artist(self._artist_id)
            if not artist:
                self.albums_loaded.emit([])
                return
            albums = artist.get("album", [])
            albums.sort(key=lambda a: a.get("year") or 0, reverse=True)
            # Deduplicate by normalized name (Navidrome can split one album into
            # multiple entries with different IDs — keep the first/newest per name)
            seen: set[str] = set()
            deduped: list[dict] = []
            for a in albums:
                key = re.sub(r"[^\w]", "", a.get("name", "").lower())
                if key not in seen:
                    seen.add(key)
                    deduped.append(a)
            self.albums_loaded.emit(deduped)
        except Exception as exc:
            logger.error(f"LoadArtistAlbumsWorker error: {exc}")
            self.error.emit(str(exc))


class LoadTopTracksWorker(QThread):
    """Looks up an artist's top 10 tracks via MusicBrainz + ListenBrainz."""

    tracks_loaded = pyqtSignal(list)   # list[dict] with keys: name, listen_count
    error = pyqtSignal(str)

    def __init__(self, artist_name: str, parent=None) -> None:
        super().__init__(parent)
        self._artist_name = artist_name

    def run(self) -> None:
        try:
            mbid = self._get_mbid(self._artist_name)
            if not mbid:
                self.error.emit("Artist not found on MusicBrainz")
                return
            tracks = self._get_top_tracks(mbid)
            self.tracks_loaded.emit(tracks)
        except Exception as exc:
            logger.error(f"LoadTopTracksWorker error: {exc}")
            self.error.emit(str(exc))

    def _get_mbid(self, name: str) -> str | None:
        resp = requests.get(
            "https://musicbrainz.org/ws/2/artist/",
            params={"query": f"artist:{name}", "fmt": "json", "limit": 1},
            headers=_MB_HEADERS,
            timeout=8,
        )
        resp.raise_for_status()
        artists = resp.json().get("artists", [])
        return artists[0]["id"] if artists else None

    def _get_top_tracks(self, mbid: str) -> list[dict]:
        resp = requests.get(
            f"https://api.listenbrainz.org/1/popularity/top-recordings-for-artist/{mbid}",
            headers=_MB_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        payload = data if isinstance(data, list) else data.get("payload", [])
        tracks = []
        for item in payload[:10]:
            tracks.append({
                "name": item.get("recording_name", "Unknown"),
                "listen_count": item.get("total_listen_count", 0),
            })
        return tracks


class ResolveTopTracksWorker(QThread):
    """Search Subsonic for each top track and resolve it to a playable dict.

    Tracks that cannot be matched keep ``_missing: True`` so the table still
    shows them (greyed-out, double-click-to-search behaviour applies).
    """

    all_resolved = pyqtSignal(list)

    def __init__(self, tracks: list[dict], artist: str, parent=None) -> None:
        super().__init__(parent)
        self._tracks = tracks
        self._artist = artist

    def run(self) -> None:
        try:
            from src.music_player.ui.workers.playlist_import import find_match
            client = SubsonicClient()

            def _resolve(t: dict) -> dict:
                match = find_match(client, t["title"], self._artist)
                return match if match else t

            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(_resolve, self._tracks))
            self.all_resolved.emit(results)
        except Exception as exc:
            logger.error(f"ResolveTopTracksWorker: {exc}")
            self.all_resolved.emit(list(self._tracks))


class LoadGenreTracksWorker(QThread):
    """Fetch all tracks for a genre via Subsonic getSongsByGenre."""

    tracks_loaded = pyqtSignal(list)
    error         = pyqtSignal(str)

    def __init__(self, genre: str, parent=None) -> None:
        super().__init__(parent)
        self._genre = genre

    def run(self) -> None:
        try:
            client = SubsonicClient()
            songs  = client.get_songs_by_genre(self._genre, count=500)
            self.tracks_loaded.emit(songs)
        except Exception as exc:
            logger.error(f"LoadGenreTracksWorker({self._genre!r}): {exc}")
            self.error.emit(str(exc))
