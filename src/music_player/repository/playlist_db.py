"""SQLite persistence for imported playlists.

Stores playlists and their per-track match state so they survive restarts.
Server playlists are not stored here — they are always fetched live.

Schema
------
playlists(id, name UNIQUE, created_at)
playlist_tracks(playlist_id, position, song_id, matched_json, raw_title,
                raw_artist, raw_duration, raw_path)

matched_json is the full Subsonic song dict serialised as JSON, or NULL when
the track has no match.  Storing the full dict avoids a network call on load.
"""

import json
import sqlite3

from src.music_player._paths import db_dir
from src.music_player.logging import get_logger

logger = get_logger(__name__)

_DB_PATH = db_dir() / "playlists.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS playlists (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS playlist_tracks (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            playlist_id  INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
            position     INTEGER NOT NULL,
            song_id      TEXT,
            matched_json TEXT,
            raw_title    TEXT NOT NULL DEFAULT '',
            raw_artist   TEXT          DEFAULT '',
            raw_duration INTEGER       DEFAULT 0,
            raw_path     TEXT          DEFAULT '',
            UNIQUE(playlist_id, position)
        );
    """)
    conn.commit()
    # Migrate existing DBs that predate the description column
    try:
        conn.execute("ALTER TABLE playlists ADD COLUMN description TEXT NOT NULL DEFAULT ''")
        conn.commit()
    except Exception:
        pass
    return conn


# ── write ─────────────────────────────────────────────────────────────

def save_playlist(name: str, matched: list, raw: list) -> None:
    """Persist or replace an imported playlist.

    Args:
        name:    Playlist name (must be unique; replaces any prior import with
                 the same name).
        matched: One entry per track — a Subsonic song dict or None if unmatched.
        raw:     One entry per track — raw parsed info dict (title, artist, …).
    """
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO playlists(name) VALUES(?) "
            "ON CONFLICT(name) DO UPDATE SET name=excluded.name",
            (name,),
        )
        row = conn.execute("SELECT id FROM playlists WHERE name=?", (name,)).fetchone()
        playlist_id = row[0]

        conn.execute("DELETE FROM playlist_tracks WHERE playlist_id=?", (playlist_id,))

        for pos, (track, raw_info) in enumerate(zip(matched, raw)):
            conn.execute(
                """INSERT INTO playlist_tracks
                   (playlist_id, position, song_id, matched_json,
                    raw_title, raw_artist, raw_duration, raw_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    playlist_id, pos,
                    track.get("id") if track else None,
                    json.dumps(track) if track else None,
                    raw_info.get("title", ""),
                    raw_info.get("artist", ""),
                    int(raw_info.get("duration") or 0),
                    raw_info.get("path", ""),
                ),
            )
        conn.commit()
        logger.info(f"playlist_db: saved '{name}' ({len(matched)} tracks)")
    except Exception as exc:
        logger.error(f"playlist_db.save_playlist failed: {exc}")
    finally:
        conn.close()


def update_track(name: str, position: int, track: dict) -> None:
    """Update a single track's match after user resolves it."""
    conn = _connect()
    try:
        row = conn.execute("SELECT id FROM playlists WHERE name=?", (name,)).fetchone()
        if not row:
            return
        conn.execute(
            "UPDATE playlist_tracks SET song_id=?, matched_json=? "
            "WHERE playlist_id=? AND position=?",
            (track.get("id"), json.dumps(track), row[0], position),
        )
        conn.commit()
    except Exception as exc:
        logger.warning(f"playlist_db.update_track failed: {exc}")
    finally:
        conn.close()


def rename_playlist(old_name: str, new_name: str, description: str = "") -> None:
    """Rename an imported playlist and optionally update its description."""
    conn = _connect()
    try:
        conn.execute(
            "UPDATE playlists SET name=?, description=? WHERE name=?",
            (new_name, description, old_name),
        )
        conn.commit()
        logger.info(f"playlist_db: renamed '{old_name}' → '{new_name}'")
    except Exception as exc:
        logger.error(f"playlist_db.rename_playlist failed: {exc}")
    finally:
        conn.close()


def update_description(name: str, description: str) -> None:
    """Update an imported playlist's description without renaming."""
    conn = _connect()
    try:
        conn.execute("UPDATE playlists SET description=? WHERE name=?", (description, name))
        conn.commit()
    except Exception as exc:
        logger.error(f"playlist_db.update_description failed: {exc}")
    finally:
        conn.close()


def delete_playlist(name: str) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM playlists WHERE name=?", (name,))
        conn.commit()
    finally:
        conn.close()


# ── read ──────────────────────────────────────────────────────────────

def load_all() -> list[dict]:
    """Return all saved playlists as a list of dicts with 'name', 'matched', 'raw'."""
    conn = _connect()
    try:
        playlists = conn.execute(
            "SELECT id, name, description FROM playlists ORDER BY name"
        ).fetchall()
        result = []
        for pl_id, pl_name, pl_desc in playlists:
            rows = conn.execute(
                "SELECT song_id, matched_json, raw_title, raw_artist, raw_duration, raw_path "
                "FROM playlist_tracks WHERE playlist_id=? ORDER BY position",
                (pl_id,),
            ).fetchall()
            matched, raw = [], []
            for song_id, matched_json, rt, ra, rd, rp in rows:
                matched.append(json.loads(matched_json) if matched_json else None)
                raw.append({"title": rt, "artist": ra, "duration": rd, "path": rp})
            result.append({"name": pl_name, "description": pl_desc, "matched": matched, "raw": raw})
        return result
    except Exception as exc:
        logger.error(f"playlist_db.load_all failed: {exc}")
        return []
    finally:
        conn.close()
