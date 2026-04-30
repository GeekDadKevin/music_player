"""In-memory image store backed by SQLite.

preload() once at startup to bulk-read the SQLite cache into RAM.
After that, get() is a plain dict lookup — no I/O, no connections.
put() writes to both the dict and SQLite so new images survive restarts.

Images are fetched on demand when a card is shown, not at startup.
"""

import sqlite3
from pathlib import Path

from src.music_player.logging import get_logger

logger = get_logger(__name__)

_DB_PATH = Path.home() / ".music-player" / "image_cache.db"

_images:    dict[str, bytes] = {}
_artists:   list[dict] = []
_albums:    list[dict] = []
_playlists: list[dict] = []
_genres:    list[dict] = []


def preload() -> int:
    """Load every row from SQLite into memory.  Returns count loaded."""
    global _images
    try:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(_DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS images"
            "(key TEXT PRIMARY KEY, data BLOB NOT NULL, source TEXT NOT NULL)"
        )
        conn.commit()
        rows = conn.execute("SELECT key, data FROM images").fetchall()
        conn.close()
        _images = {k: bytes(v) for k, v in rows}
        logger.info(f"image_store: preloaded {len(_images)} images from SQLite")
        return len(_images)
    except Exception as exc:
        logger.error(f"image_store.preload failed: {exc}")
        return 0


def get(key: str) -> bytes | None:
    return _images.get(key)


def has(key: str) -> bool:
    return key in _images


def put(key: str, data: bytes, source: str) -> None:
    _images[key] = data
    try:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "INSERT OR REPLACE INTO images(key, data, source) VALUES(?,?,?)",
            (key, data, source),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning(f"image_store.put SQLite write failed ({key}): {exc}")


def set_artists(artists: list[dict]) -> None:
    global _artists
    _artists = list(artists)


def get_artists() -> list[dict]:
    return _artists


def set_albums(albums: list[dict]) -> None:
    global _albums
    _albums = list(albums)


def get_albums() -> list[dict]:
    return _albums


def set_playlists(playlists: list[dict]) -> None:
    global _playlists
    _playlists = list(playlists)


def get_playlists() -> list[dict]:
    return _playlists


def set_genres(genres: list[dict]) -> None:
    global _genres
    _genres = list(genres)


def get_genres() -> list[dict]:
    return _genres
