

from PyQt6.QtCore import QThread, pyqtSignal
from src.music_player.repository.subsonic_client import SubsonicClient
from src.music_player.logging import get_logger

logger = get_logger(__name__)


class ArtistListWorker(QThread):
    artists_loaded = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        logger.info("ArtistListWorker instantiated")
        self._client = SubsonicClient()

    def run(self):
        logger.info("ArtistListWorker.run() started")
        try:
            artists = self._client.get_artists()
            logger.info(f"Fetched {len(artists)} artists from SubsonicClient, emitting")
            self.artists_loaded.emit(artists)
        except Exception as e:
            logger.error(f"Exception in ArtistListWorker.run: {e}")
            self.error.emit(str(e))
