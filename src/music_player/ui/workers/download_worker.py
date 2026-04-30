"""SearchAndPlayWorker — find a track in Subsonic so Octofiesta can download it.

Playing the stream URL is enough to trigger an Octofiesta download; no explicit
HEAD request is needed.  This worker just resolves the Subsonic ID for a track
that is shown in the UI but not yet in the local library.
"""

from PyQt6.QtCore import QThread, pyqtSignal

from src.music_player.logging import get_logger
from src.music_player.repository.subsonic_client import SubsonicClient

logger = get_logger(__name__)


class SearchAndPlayWorker(QThread):
    """Search Subsonic for a track by title/artist and emit the matched dict.

    The caller should connect ``found`` and call play_track on the bridge.
    If no match is found the signal is not emitted and nothing happens.
    """

    found = pyqtSignal(dict)

    def __init__(self, title: str, artist: str, parent=None) -> None:
        super().__init__(parent)
        self._title  = title
        self._artist = artist

    def run(self) -> None:
        try:
            from src.music_player.ui.workers.playlist_import import find_match
            client = SubsonicClient()
            match  = find_match(client, self._title, self._artist)
            if match:
                logger.info(f"Resolved missing track {self._title!r} → id={match['id']}")
                self.found.emit(match)
            else:
                logger.info(f"Missing track not found in library: {self._title!r}")
        except Exception as exc:
            logger.error(f"SearchAndPlayWorker error: {exc}")
