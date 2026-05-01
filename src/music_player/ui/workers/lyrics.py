"""Background worker that fetches lyrics for the current track.

Tries getLyricsBySongId (OpenSubsonic) for synced lyrics first, then
falls back to the plain getLyrics endpoint.

Emitted payload:
    {
        "synced": bool,
        "lines": [
            {"t": float, "text": str},   # when synced=True (t in seconds)
            str,                          # when synced=False (plain lines)
        ]
    }
"""

from PyQt6.QtCore import QThread, pyqtSignal

from src.music_player.logging import get_logger

logger = get_logger(__name__)


class LyricsWorker(QThread):
    loaded = pyqtSignal(dict)

    def __init__(self, song_id: str, artist: str, title: str, parent=None) -> None:
        super().__init__(parent)
        self._song_id = song_id
        self._artist = artist
        self._title = title
        self.setObjectName("LyricsWorker")

    def run(self) -> None:
        from src.music_player.services import get_repository
        repo = get_repository()

        structured = repo.get_lyrics_by_id(self._song_id)
        if structured:
            raw_lines = structured.get("line", [])
            if raw_lines:
                if structured.get("synced"):
                    lines = [
                        {"t": l.get("start", 0) / 1000.0, "text": l.get("value", "")}
                        for l in raw_lines
                    ]
                    self.loaded.emit({"synced": True, "lines": lines})
                    return
                else:
                    lines = [l.get("value", "") for l in raw_lines]
                    self.loaded.emit({"synced": False, "lines": [l for l in lines if l]})
                    return

        text = repo.get_lyrics(self._artist, self._title)
        if text:
            lines = [l for l in text.splitlines() if l.strip()]
            self.loaded.emit({"synced": False, "lines": lines})
            return

        self.loaded.emit({"synced": False, "lines": []})
