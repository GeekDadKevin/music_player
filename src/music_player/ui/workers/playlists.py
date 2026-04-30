from PyQt6.QtCore import QThread, pyqtSignal

from src.music_player.logging import get_logger
from src.music_player.repository.subsonic_client import SubsonicClient

logger = get_logger(__name__)


class LoadPlaylistsWorker(QThread):
    """Fetch the server playlist index."""

    playlists_loaded = pyqtSignal(list)  # list[dict]
    error = pyqtSignal(str)

    def run(self) -> None:
        try:
            client = SubsonicClient()
            self.playlists_loaded.emit(client.get_playlists())
        except Exception as exc:
            logger.error(f"LoadPlaylistsWorker: {exc}")
            self.error.emit(str(exc))


class LoadPlaylistTracksWorker(QThread):
    """Fetch all tracks for a single server playlist."""

    tracks_loaded = pyqtSignal(list, dict)  # tracks, playlist_info
    error = pyqtSignal(str)

    def __init__(self, playlist_id: str, parent=None) -> None:
        super().__init__(parent)
        self._playlist_id = playlist_id

    def run(self) -> None:
        try:
            client = SubsonicClient()
            playlist = client.get_playlist(self._playlist_id)
            if not playlist:
                self.tracks_loaded.emit([], {})
                return
            tracks = playlist.get("entry", [])
            for t in tracks:
                if not t.get("album"):
                    t["album"] = ""
            self.tracks_loaded.emit(tracks, playlist)
        except Exception as exc:
            logger.error(f"LoadPlaylistTracksWorker: {exc}")
            self.error.emit(str(exc))
