"""On-demand image loaders.

Images are fetched when a view needs them, not at startup.
Results are stored in image_store (memory + SQLite) so the second access is instant.

ArtistImageLoader  — one artist, fetches from Deezer → iTunes
AlbumCoverLoader   — one album, fetches from MusicBrainz CAA → Subsonic fallback
ImageQueueWorker   — batch of artists, parallel pool, used by the Artists grid
"""

import concurrent.futures

from PyQt6.QtCore import Qt, QThread, pyqtSignal

import src.music_player.image_store as image_store
from src.music_player.logging import get_logger
from src.music_player.ui.components.musicbrainz_image import (
    fetch_album_cover_bytes,
    fetch_artist_image_bytes,
)

logger = get_logger(__name__)

_POOL_SIZE = 8

# Keeps a Python reference to every running worker.  Without this, the GC
# can collect a parentless QThread object while its C++ thread is still
# running, triggering "QThread: Destroyed while thread is still running".
_live: set = set()


def _launch(worker) -> None:
    """Hold a live reference until the thread finishes, then clean up.

    Use instead of worker.start() for any loader that has no Qt parent.

    QueuedConnection ensures the cleanup lambda runs in the main event loop,
    not in the worker thread.  Without this, Python's __del__ can fire from
    the worker thread and try to destroy the QThread C++ object from the
    wrong thread — which is what causes 'QThread: Destroyed while running'.
    """
    _live.add(worker)
    worker.finished.connect(
        lambda: _live.discard(worker),
        Qt.ConnectionType.QueuedConnection,
    )
    worker.finished.connect(worker.deleteLater)
    worker.start()


# ── single artist ─────────────────────────────────────────────────────

class ArtistImageLoader(QThread):
    """Fetch one artist image (cache-first, then Deezer/iTunes)."""

    loaded = pyqtSignal(bytes)

    def __init__(self, artist_name: str, parent=None) -> None:
        super().__init__(parent)
        self._name = artist_name

    def run(self) -> None:
        key  = f"artist:{self._name.lower()}"
        data = image_store.get(key)
        if data is None:
            data = fetch_artist_image_bytes(self._name)
            image_store.put(key, data or b"", source="fetched")
        self.loaded.emit(data or b"")


# ── single album cover ────────────────────────────────────────────────

class AlbumCoverLoader(QThread):
    """Fetch one album cover (cache-first, then Subsonic, then Deezer)."""

    loaded = pyqtSignal(bytes)

    def __init__(
        self,
        cover_art_id: str = "",
        artist: str = "",
        album: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._cover_art_id = cover_art_id
        self._artist       = artist
        self._album        = album

    def run(self) -> None:
        key = (
            f"album:{self._cover_art_id}"
            if self._cover_art_id
            else f"album:ext:{self._artist}:{self._album}".lower()
        )
        data = image_store.get(key)
        if data is None:
            data = self._fetch()
            image_store.put(key, data or b"", source="fetched")
        self.loaded.emit(data or b"")

    def _fetch(self) -> bytes:
        # MusicBrainz CAA → Deezer → Subsonic (external sources first for quality)
        if self._artist or self._album:
            data = fetch_album_cover_bytes(self._artist, self._album)
            if data:
                return data

        # Fall back to Subsonic server art
        if self._cover_art_id:
            try:
                from src.music_player.repository.subsonic_client import SubsonicClient
                return SubsonicClient().get_cover_art(self._cover_art_id, size=300)
            except Exception as exc:
                logger.debug(f"Subsonic cover art unavailable ({self._cover_art_id}): {exc}")

        return b""


# ── batch artist loader (used by Artists grid) ────────────────────────

class ImageQueueWorker(QThread):
    """Fetch a batch of artist images in parallel, emitting as each completes."""

    image_ready = pyqtSignal(str, bytes)   # artist_name, raw bytes

    def __init__(self, artists: list[tuple[str, str]], parent=None) -> None:
        super().__init__(parent)
        self._artists = artists   # [(name, cover_art_id), ...]

    def run(self) -> None:
        # Emit cached images immediately
        to_fetch: list[str] = []
        for name, _ in self._artists:
            key  = f"artist:{name.lower()}"
            data = image_store.get(key)
            if data is not None:
                self.image_ready.emit(name, data)
            else:
                to_fetch.append(name)

        if not to_fetch:
            return

        with concurrent.futures.ThreadPoolExecutor(max_workers=_POOL_SIZE) as pool:
            futures = {pool.submit(fetch_artist_image_bytes, name): name for name in to_fetch}
            for future in concurrent.futures.as_completed(futures):
                name = futures[future]
                try:
                    data = future.result() or b""
                except Exception as exc:
                    logger.warning(f"Artist image fetch failed ({name}): {exc}")
                    data = b""
                image_store.put(f"artist:{name.lower()}", data, source="fetched")
                self.image_ready.emit(name, data)
