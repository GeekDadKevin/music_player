"""Play history and per-song play counts — persisted to ~/.music-player/plays.db.

Tables
------
play_history   — one row per counted play (song_id, title, artist, played_at)
play_counts    — running total per song_id (upserted on every counted play)

A play is only recorded when it crosses the threshold set in AppSettings
(min_play_seconds).  The bridge calls record_play() after confirming the
threshold was crossed.
"""

import sqlite3
from pathlib import Path

from src.music_player.logging import get_logger

logger = get_logger(__name__)

_DB = Path.home() / ".music-player" / "plays.db"


def _connect() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS play_history (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            song_id      TEXT    NOT NULL,
            title        TEXT    NOT NULL DEFAULT '',
            artist       TEXT    NOT NULL DEFAULT '',
            album        TEXT             DEFAULT '',
            cover_art_id TEXT             DEFAULT '',
            played_at    TEXT    NOT NULL DEFAULT (datetime('now')),
            play_seconds INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS play_counts (
            song_id      TEXT PRIMARY KEY,
            title        TEXT NOT NULL DEFAULT '',
            artist       TEXT NOT NULL DEFAULT '',
            album        TEXT          DEFAULT '',
            cover_art_id TEXT          DEFAULT '',
            genre        TEXT          DEFAULT '',
            play_count   INTEGER NOT NULL DEFAULT 0,
            last_played  TEXT    NOT NULL DEFAULT (datetime('now'))
        );
    """)
    # Add genre column to existing DBs that predate this field
    try:
        conn.execute("ALTER TABLE play_counts ADD COLUMN genre TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass
    return conn


# ── write ─────────────────────────────────────────────────────────────

def record_play(track: dict, seconds_played: int) -> None:
    """Record one counted play for track.  Updates both history and counts."""
    song_id      = track.get("id", "")
    title        = track.get("title", "")
    artist       = track.get("artist", "")
    album        = track.get("album", "")
    cover_art_id = track.get("coverArt", "")
    genre        = track.get("genre", "")

    if not song_id:
        return

    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO play_history(song_id,title,artist,album,cover_art_id,play_seconds) "
            "VALUES(?,?,?,?,?,?)",
            (song_id, title, artist, album, cover_art_id, seconds_played),
        )
        conn.execute(
            """INSERT INTO play_counts(song_id,title,artist,album,cover_art_id,genre,play_count,last_played)
               VALUES(?,?,?,?,?,?,1,datetime('now'))
               ON CONFLICT(song_id) DO UPDATE SET
                   play_count  = play_count + 1,
                   last_played = datetime('now'),
                   title       = excluded.title,
                   artist      = excluded.artist,
                   genre       = CASE WHEN excluded.genre != '' THEN excluded.genre ELSE genre END""",
            (song_id, title, artist, album, cover_art_id, genre),
        )
        conn.commit()
        logger.debug(f"Recorded play: {title!r} by {artist!r} ({seconds_played}s)")
    except Exception as exc:
        logger.error(f"play_history_db.record_play: {exc}")
    finally:
        conn.close()


# ── read ──────────────────────────────────────────────────────────────

def get_recent_artists(limit: int = 5) -> list[dict]:
    """Return the most recently played distinct artists (newest first)."""
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT artist, MAX(played_at) AS last_played
               FROM play_history
               GROUP BY artist
               ORDER BY last_played DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [{"artist": r[0], "last_played": r[1]} for r in rows]
    finally:
        conn.close()


def get_top_songs(limit: int = 50) -> list[dict]:
    """Return songs ordered by play count descending."""
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT song_id, title, artist, album, cover_art_id, play_count, last_played
               FROM play_counts ORDER BY play_count DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r[0], "title": r[1], "artist": r[2],
                "album": r[3], "coverArt": r[4],
                "play_count": r[5], "last_played": r[6],
            }
            for r in rows
        ]
    finally:
        conn.close()


def get_play_history(limit: int = 200) -> list[dict]:
    """Return recent plays newest-first, one row per play event."""
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT song_id, title, artist, album, cover_art_id, played_at, play_seconds
               FROM play_history ORDER BY played_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            {
                "id":          r[0],
                "title":       r[1],
                "artist":      r[2],
                "album":       r[3],
                "coverArt":    r[4],
                "played_at":   r[5],
                "play_seconds": r[6],
                "duration":    r[6],   # TrackTable-compatible field
            }
            for r in rows
        ]
    finally:
        conn.close()


def get_top_artists(limit: int = 10) -> list[dict]:
    """Return artists ranked by total play count descending."""
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT artist, SUM(play_count) AS total
               FROM play_counts WHERE artist != ''
               GROUP BY artist ORDER BY total DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [{"artist": r[0], "play_count": r[1]} for r in rows]
    finally:
        conn.close()


def get_top_genres(limit: int = 10) -> list[dict]:
    """Return genres ranked by total play count descending."""
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT genre, SUM(play_count) AS total
               FROM play_counts
               WHERE genre != '' AND genre IS NOT NULL
               GROUP BY genre ORDER BY total DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [{"genre": r[0], "play_count": r[1]} for r in rows]
    finally:
        conn.close()


def get_top_artist_for_genre(genre: str) -> str | None:
    """Return the most-played artist for a given genre, or None."""
    conn = _connect()
    try:
        row = conn.execute(
            """SELECT artist, SUM(play_count) AS total
               FROM play_counts WHERE genre=? AND artist!=''
               GROUP BY artist ORDER BY total DESC LIMIT 1""",
            (genre,),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def get_play_count(song_id: str) -> int:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT play_count FROM play_counts WHERE song_id=?", (song_id,)
        ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()
