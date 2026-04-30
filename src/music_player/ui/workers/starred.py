from PyQt6.QtCore import QThread, pyqtSignal

from src.music_player.logging import get_logger
from src.music_player.repository.subsonic_client import SubsonicClient

logger = get_logger(__name__)


class LoadStarredWorker(QThread):
    """Fetch all starred (hearted) songs from the server."""

    songs_loaded = pyqtSignal(list)   # list[dict] — Subsonic song dicts
    error        = pyqtSignal(str)

    def run(self) -> None:
        try:
            client = SubsonicClient()
            songs  = client.get_starred_songs()
            self.songs_loaded.emit(songs)
        except Exception as exc:
            logger.error(f"LoadStarredWorker: {exc}")
            self.error.emit(str(exc))


class StarToggleWorker(QThread):
    """Star or unstar a single song in the background."""

    done   = pyqtSignal(str, bool)   # song_id, new_starred_state
    failed = pyqtSignal(str)

    def __init__(self, song_id: str, star: bool, parent=None) -> None:
        super().__init__(parent)
        self._song_id = song_id
        self._star    = star

    def run(self) -> None:
        try:
            client = SubsonicClient()
            if self._star:
                ok = client.star_song(self._song_id)
            else:
                ok = client.unstar_song(self._song_id)
            if ok:
                self.done.emit(self._song_id, self._star)
            else:
                self.failed.emit(f"Server rejected {'star' if self._star else 'unstar'}")
        except Exception as exc:
            self.failed.emit(str(exc))
