import sqlite3
from pathlib import Path

from src.music_player.logging import get_logger

logger = get_logger(__name__)

_DB_PATH = Path.home() / ".music-player" / "image_cache.db"


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS images ("
        "  key TEXT PRIMARY KEY,"
        "  data BLOB NOT NULL,"
        "  source TEXT NOT NULL"
        ")"
    )
    conn.commit()
    return conn


class ImageCache:
    """Thread-safe SQLite image cache.  One connection per instance; call close() when done."""

    def __init__(self) -> None:
        self._conn = _connect()

    def get(self, key: str) -> bytes | None:
        row = self._conn.execute(
            "SELECT data FROM images WHERE key = ?", (key,)
        ).fetchone()
        if row:
            logger.debug(f"ImageCache hit: {key}")
            return bytes(row[0])
        return None

    def put(self, key: str, data: bytes, source: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO images (key, data, source) VALUES (?, ?, ?)",
            (key, data, source),
        )
        self._conn.commit()
        logger.debug(f"ImageCache stored: {key} ({len(data)} bytes, source={source})")

    def close(self) -> None:
        self._conn.close()
