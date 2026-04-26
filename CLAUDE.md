# Music Player

A desktop music player (PyQt6 GUI) that streams from an OpenSubsonic server.

## Commands
- `uv run music-player` — launch the GUI
- `uv run music-agent` — launch the Claude coding assistant
- `uv run pytest` — run tests

## Setup
```
cp .env.example .env   # fill in SUBSONIC_* and ANTHROPIC_API_KEY
uv sync
```

---

## Architecture

### Layer Decomposition

```
Domain          player/audio.py         Track dataclass, AudioPlayer (mpv)
                api/subsonic_sync.py    SubsonicSyncClient
Application     ui/playback_controller  PlaybackController — audio, poll, lookahead, cover art
                ui/library_controller   LibraryController — worker spawning, search
Infrastructure  ui_settings.py          UISettings persistence (JSON)
                ui/theme.py             build_stylesheet() CSS generation
                ui/workers/             QThread workers (one API call each)
                logging.py              get_logger
Interface       ui/app.py               MusicPlayerWindow — layout + signal wiring only
                ui/components/          Pages and shared widgets
```

### Core Files
| File | Purpose |
|------|---------|
| `src/music_player/config.py` | `Settings` loaded from `.env` via pydantic-settings |
| `src/music_player/api/subsonic.py` | `SubsonicClient` — async httpx wrapper (not used in UI) |
| `src/music_player/api/subsonic_sync.py` | `SubsonicSyncClient` — sync httpx wrapper used by all workers |
| `src/music_player/player/audio.py` | `AudioPlayer` (mpv backend) + `Track` dataclass |
| `src/music_player/logging.py` | Centralized logging setup (`get_logger`) |
| `src/music_player/ui_settings.py` | `UISettings` dataclass + `load_ui_settings`/`save_ui_settings` (JSON at `~/.music-player/`) |
| `src/music_player/ui/theme.py` | `build_stylesheet()` — generates full CSS from `DARK`/`LIGHT` palette + accent color |
| `src/agent/` | Claude `claude-opus-4-7` coding assistant for this project |

### UI Files
| File | Purpose |
|------|---------|
| `src/music_player/ui/app.py` | `MusicPlayerWindow` — layout + signal wiring only |
| `src/music_player/ui/playback_controller.py` | `PlaybackController` — audio, poll timer, lookahead, cover art |
| `src/music_player/ui/library_controller.py` | `LibraryController` — worker spawning, active-worker tracking, search |
| `src/music_player/ui/components/player_bar.py` | `PlayerBar` — transport, progress, volume |
| `src/music_player/ui/components/sidebar.py` | `Sidebar` — navigation list |
| `src/music_player/ui/components/track_table.py` | `TrackTable` — shared track listing with pulse animation |
| `src/music_player/ui/components/album_header.py` | `AlbumHeader` — cover art + metadata |
| `src/music_player/ui/components/artists_page.py` | `ArtistsPage` — 3-pane: artists | albums | tracks |
| `src/music_player/ui/components/playlist_page.py` | `PlaylistPage` — 2-pane: playlists | tracks |
| `src/music_player/ui/components/queue_page.py` | `QueuePage` — current queue with Now Playing header |
| `src/music_player/ui/components/settings_page.py` | `SettingsPage` — appearance, playback, server info |
| `src/music_player/ui/components/utils.py` | `load_album_tracks_for_table()` + formatting helpers |

### Worker Threads
| File | Class(es) | Notes |
|------|-----------|-------|
| `src/music_player/ui/workers/artists.py` | `LoadArtistsWorker`, `LoadArtistAlbumsWorker` | One Subsonic call each |
| `src/music_player/ui/workers/albums.py` | `LoadAlbumTracksWorker` | Used by Artists tab via `utils.py` |
| `src/music_player/ui/workers/playlists.py` | `LoadPlaylistsWorker`, `LoadPlaylistTracksWorker` | |
| `src/music_player/ui/workers/search.py` | `SearchWorker` | `search3` — populates Library tab |
| `src/music_player/ui/workers/cover_art.py` | `LoadCoverArtWorker` | Accepts artist ID or song ID |
| `src/music_player/ui/workers/lookahead.py` | `LookaheadWorker` | Warms next track stream URL |

---

## Data Flow

### Artists Tab (one API call per user action)
- Tab open → `getArtists` → artist list
- Artist click → `getArtist(id)` → album list + cover art
- Album click → `getAlbum(id)` → `Track` list → `TrackTable`

### Library Tab (search-driven, zero startup calls)
- User types 2+ chars → `SearchWorker` → `search3?query=<text>` → Library table
- Clearing search clears the table

### Playback
- Double-click track → `set_queue(all_tracks, start=row)` → `_play_track(track)`
- `_poll_playback` (500 ms QTimer) → reads mpv `eof_reached`, `time_pos`, `duration`
- Track end detected via `eof_reached` → `_next_track()`
- 5 s after track start → `LookaheadWorker` warms next stream URL

---

## Track Dataclass (`player/audio.py`)
```python
@dataclass
class Track:
    id: str
    title: str
    artist: str
    album: str
    duration: int       # seconds
    stream_url: str     # built by client.stream_url(song_id) — valid indefinitely
```
All workers that emit tracks **must** produce `list[Track]` (not raw dicts).
Always build `stream_url` via `self._client.stream_url(song.get("id", ""))`.

---

## Known Anti-Patterns & Failure Points

### 🔴 Critical

### 🟠 High

**`utils.py` couples UI to worker implementation**
— `load_album_tracks_for_table()` directly imports `LoadAlbumTracksWorker`. A UI utility should not depend on a concrete worker class.

### 🟡 Medium

**Inconsistent worker cleanup**
— `_active_workers` tracks playlist/artist/search workers but not `_cover_worker` or `_lookahead_worker`. `closeEvent` won't join them properly on rapid exit.

**`SettingsPage.stylesheet_changed` connects directly to `QApplication.setStyleSheet`**
— Global app state mutated by a component-level signal. Intermediate handler in `MusicPlayerWindow` would allow validation, logging, and future batching.

### 🟢 Low

**Hardcoded timeouts** — API: 30 s (`subsonic_sync.py:29`), lookahead: 20 s (`lookahead.py:20`). Move to `Settings` or `UISettings`.

**Title/artist truncation hardcoded to 22 chars** (`player_bar.py:184-185`). Should derive from widget width or be a constant.

---

## OpenSubsonic Auth
Token-based: `t = md5(password + salt)`, `s = random_salt`. All requests include
`?u=&t=&s=&v=1.16.1&c=music-player&f=json`.

## SubsonicSyncClient Methods
| Method | Subsonic Endpoint |
|--------|------------------|
| `get_artists()` | `getArtists` — full artist index |
| `get_artist(id)` | `getArtist` — returns artist dict with `"album": [...]` |
| `get_album(id)` | `getAlbum` — returns album dict with `"song": [...]` |
| `get_all_songs(page_size)` | `search3?query=""` paginated |
| `get_song(id)` | `getSong` |
| `get_cover_art(id)` | `getCoverArt` — accepts song ID, album ID, or artist ID |
| `get_playlists()` | `getPlaylists` |
| `get_playlist(id)` | `getPlaylist` |
| `search(query)` | `search3` |
| `stream_url(id)` | builds stream URL with auth params (valid indefinitely) |

---

## Conventions

- **Always ensure `logger = get_logger(__name__)` is defined at the top of each module before use.**
- If you encounter a NameError or missing import for logger or any other shared utility, add the correct import and initialization at the top of the file without asking.
- PyQt6 only (not PyQt5, not PySide6)
- Sync httpx (`SubsonicSyncClient`) in `QThread.run()` only — never block the main thread
- Full type hints on all public functions
- Config never hardcoded — always from `Settings` or `UISettings`
- No `print()` — use `logger` or `self._status_label.setText()`
- All logging via `from music_player.logging import get_logger`
- Logs written to `./logs/music_player.log`

## Consistency & Reuse

- **Any change must be applied throughout the app for coherence.**
- **Never duplicate logic — one canonical implementation per operation.**
- `load_album_tracks_for_table()` in `utils.py` is the single entry point for album track loading — never inline a `LoadAlbumTracksWorker`.
- `TrackTable` is the single shared component for all track listings.
- All workers that produce tracks must emit `list[Track]` — never raw dicts.
- All colors must come from `theme.py` palette via the stylesheet — never inline `setStyleSheet` with hardcoded hex values in components.
