from PyQt6.QtCore import QThread, pyqtSignal

from src.music_player.logging import get_logger
from src.music_player.repository.subsonic_client import SubsonicClient

logger = get_logger(__name__)


class SearchWorker(QThread):
    """Search the Subsonic library and return matching song dicts."""

    results_ready = pyqtSignal(list)
    error         = pyqtSignal(str)

    def __init__(self, query: str, song_count: int = 50, parent=None) -> None:
        super().__init__(parent)
        self._query      = query
        self._song_count = song_count

    def run(self) -> None:
        try:
            client = SubsonicClient()
            results = client.search(self._query, song_count=self._song_count)
            self.results_ready.emit(results)
        except Exception as exc:
            logger.error(f"SearchWorker: {exc}")
            self.error.emit(str(exc))


class SearchAllWorker(QThread):
    """Search artists, albums, and songs in one request."""

    results_ready = pyqtSignal(dict)   # {artists, albums, tracks}
    error         = pyqtSignal(str)

    def __init__(self, query: str, parent=None) -> None:
        super().__init__(parent)
        self._query = query

    def run(self) -> None:
        try:
            client = SubsonicClient()
            self.results_ready.emit(client.search_all(self._query))
        except Exception as exc:
            logger.error(f"SearchAllWorker: {exc}")
            self.error.emit(str(exc))
