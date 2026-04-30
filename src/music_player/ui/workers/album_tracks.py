from PyQt6.QtCore import QThread, pyqtSignal

from src.music_player.logging import get_logger
from src.music_player.repository.subsonic_client import SubsonicClient

logger = get_logger(__name__)


class LoadAlbumTracksWorker(QThread):
    """Fetch all tracks for an album, merging multiple Navidrome IDs and
    augmenting with the full MusicBrainz tracklist so missing tracks are visible.

    Emits tracks_loaded with a list where tracks not in the library have
    ``_missing: True``.  The album_info dict in the second arg is from Subsonic.
    """

    tracks_loaded = pyqtSignal(list, dict)
    error         = pyqtSignal(str)

    def __init__(
        self,
        album_id:   str,
        extra_ids:  list | None = None,
        artist:     str = "",
        album_name: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._primary    = album_id
        self._all_ids    = [album_id] + [i for i in (extra_ids or []) if i != album_id]
        self._artist     = artist
        self._album_name = album_name

    def run(self) -> None:
        try:
            artist     = self._artist
            album_name = self._album_name
            client     = SubsonicClient()

            # ── Step 1: MusicBrainz tracklist first (works from cache offline) ──
            mb_tracks: list[dict] = []
            if artist and album_name:
                from src.music_player.ui.components.musicbrainz_image import (
                    _normalize_title,
                    fetch_tracklist,
                )
                mb_tracks = fetch_tracklist(artist, album_name)

            if mb_tracks:
                # Emit everything greyed-out so the UI shows immediately
                initial = [
                    {
                        "title":    t["title"],
                        "track":    int(t["track_number"] or 0),
                        "duration": t["duration"],
                        "artist":   artist,
                        "album":    album_name,
                        "_missing": True,
                    }
                    for t in mb_tracks
                ]
                initial.sort(key=lambda t: int(t.get("track") or 999))
                self.tracks_loaded.emit(initial, {})

            # ── Step 2: Fetch owned tracks from Navidrome ──────────────────────
            all_tracks: list[dict] = []
            album_info: dict       = {}

            for aid in self._all_ids:
                album = client.get_album(aid)
                if not album:
                    continue
                if not album_info:
                    album_info = album
                for t in album.get("song", []):
                    if not t.get("album"):
                        t["album"] = album.get("name", "")
                    if not t.get("artist"):
                        t["artist"] = album.get("artist", "")
                    all_tracks.append(t)

            if not all_tracks and not mb_tracks:
                self.tracks_loaded.emit([], {})
                return

            # Deduplicate Navidrome tracks by id
            seen_ids: set[str] = set()
            deduped: list[dict] = []
            for t in all_tracks:
                tid = t.get("id", "")
                if tid not in seen_ids:
                    seen_ids.add(tid)
                    deduped.append(t)

            if not mb_tracks:
                # No MB data — just emit Navidrome tracks sorted
                deduped.sort(key=lambda t: (int(t.get("discNumber") or 1), int(t.get("track") or 999)))
                self.tracks_loaded.emit(deduped, album_info)
                return

            # ── Step 3: Merge — ungrey tracks we own, keep others as _missing ──
            from src.music_player.ui.components.musicbrainz_image import _normalize_title

            library_nums: set[int] = set()
            library_titles: set[str] = set()
            for t in deduped:
                num = t.get("track")
                if num is not None:
                    try:
                        library_nums.add(int(num))
                    except (TypeError, ValueError):
                        pass
                library_titles.add(_normalize_title(t.get("title", "")))

            merged: list[dict] = list(deduped)  # owned tracks (playable)
            for mb in mb_tracks:
                mb_num = int(mb["track_number"] or 0)
                if mb_num and mb_num in library_nums:
                    continue
                if _normalize_title(mb["title"]) in library_titles:
                    continue
                merged.append({
                    "title":    mb["title"],
                    "track":    mb_num or 999,
                    "duration": mb["duration"],
                    "artist":   artist or album_info.get("artist", ""),
                    "album":    album_name or album_info.get("name", ""),
                    "_missing": True,
                })

            merged.sort(key=lambda t: (int(t.get("discNumber") or 1), int(t.get("track") or 999)))
            self.tracks_loaded.emit(merged, album_info)

        except Exception as exc:
            logger.error(f"LoadAlbumTracksWorker error: {exc}")
            self.error.emit(str(exc))
