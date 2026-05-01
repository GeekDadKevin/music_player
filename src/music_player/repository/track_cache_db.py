"""Track metadata cache — SQLite persistence so MB/Navidrome data survives offline.

Keys follow a simple scheme:
    mb_tracklist:{artist_lower}|||{album_lower}   MusicBrainz full tracklist
    nav_albums:{artist_id}                         Navidrome artist album list
    nav_album:{album_id}                           Navidrome album + track list

Values are JSON-encoded Python objects (list or dict).
"""

import json
import sqlite3

from src.music_player._paths import db_dir
from src.music_player.logging import get_logger

logger = get_logger(__name__)

_DB = db_dir() / "track_cache.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS track_cache "
        "(cache_key TEXT PRIMARY KEY, data TEXT NOT NULL, "
        "cached_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.commit()
    return conn


def get_cached(key: str):
    """Return deserialized cached value, or None if missing."""
    try:
        conn = _connect()
        row = conn.execute(
            "SELECT data FROM track_cache WHERE cache_key=?", (key,)
        ).fetchone()
        conn.close()
        return json.loads(row[0]) if row else None
    except Exception as exc:
        logger.debug(f"track_cache get({key}): {exc}")
        return None


def set_cached(key: str, value) -> None:
    """Serialize and store value under key."""
    try:
        conn = _connect()
        conn.execute(
            "INSERT OR REPLACE INTO track_cache(cache_key, data, cached_at) "
            "VALUES(?, ?, datetime('now'))",
            (key, json.dumps(value)),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.debug(f"track_cache set({key}): {exc}")
