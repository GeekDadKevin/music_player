from PyQt6.QtCore import QThread, pyqtSignal

from src.music_player.logging import get_logger
from src.music_player.repository.subsonic_client import SubsonicClient

logger = get_logger(__name__)


class ShuffleWorker(QThread):
    """Fetch 30 random songs from the server and emit them as a playable list."""

    done = pyqtSignal(list)

    def run(self) -> None:
        try:
            client = SubsonicClient()
            songs  = client.get_random_songs(count=30)
            logger.info(f"ShuffleWorker: {len(songs)} random songs")
            self.done.emit(songs)
        except Exception as exc:
            logger.error(f"ShuffleWorker error: {exc}")
            self.done.emit([])
