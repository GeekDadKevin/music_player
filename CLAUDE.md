# Music Player

A desktop music player (PyQt6 GUI) that streams from an OpenSubsonic server (Navidrome).

## Git
All git operations (commit, push, branch, merge, rebase) are handled by the user.
Do not run any git commands unless explicitly asked.

---

## CRASH-PREVENTION RULES (hard-won — do not violate)

These rules were derived from 3 days of debugging deterministic crashes on PyQt6 6.11 / Python 3.13.9 / Windows 11 24H2.

### 1. Never override `nativeEvent()` in any QMainWindow/QWidget subclass
PyQt6 6.11 installs a native event filter **during** `CreateWindowExW` when `nativeEvent` is overridden. This causes a deterministic `access violation` inside `window.show()` — every single launch, no exception. The crash is silent and produces no useful Python traceback.

For Win32 hotkey dispatch, use a `_HotkeySignaler(QObject)` with `pyqtSignal(int)` — a pump thread emits the signal and Qt delivers it to the main thread via queued connection. See `app.py::_HotkeySignaler` and `_register_global_media_keys()`.

### 2. Never set `QSurfaceFormat.setDefaultFormat()` at startup
A global 3.3-Core format forces Qt to create a Core Profile WGL context for the main window's backing store during `window.show()`, which crashes on some GPU driver configurations. Set the format per-widget inside `MilkdropWidget.__init__()` with `self.setFormat(fmt)` instead.

### 3. Never import `milkdrop_widget` at module level in any UI file
`milkdrop_widget.py` loads projectM-4.dll, GLEW, and PortAudio (via sounddevice) at module-import time. Their `DllMain` hooks can crash during `CreateWindowExW`. Import it lazily inside `VisualizerPanel.showEvent()` (only when the user opens the visualizer).

### 4. Never create `MpvAudioBackend` before `window.show()` returns
libmpv starts internal C threads. Defer all libmpv creation until after `window.show()` completes. Use `PlaybackBridge.init_audio()` called from `on_ready()` after `window.show()`. In `MpvAudioBackend.__init__()`, use `mpv.MPV(start_event_thread=False)` and start the event thread manually via `start_event_thread()` inside `init_audio()`.

### 5. Never share a single `httpx.Client` across concurrent `ThreadPoolExecutor` tasks
Sharing one client causes concurrent SSL connection-pool operations that corrupt OpenSSL state → `Windows fatal exception: code 0xe24c4a02` + access violation in `ssl.py _SSLContext.__new__`. Each task must create its own `SubsonicClient()`:
```python
# WRONG
af = pool.submit(client.get_artists)
# CORRECT
af = pool.submit(lambda: SubsonicClient().get_artists())
```

### 6. Use one shared httpx.Client; create it before any DLL loads
After `libmpv.dll` enters the process, creating a new `ssl.SSLContext` (via `httpx.Client()`) crashes on Python 3.13.9 / Windows 11 with code `0xe24c4a02`. Fix: `_http.py` has a `_SHARED_SESSION` singleton. `main()` calls `_get_session()` before `QApplication` to establish the one ssl context. All `SubsonicHttp` instances reuse it. No new ssl context is ever created post-DLL-load.

Also pre-import `requests` so urllib3's ssl init happens on the main thread:
```python
from src.music_player.repository._http import _get_session as _warm_http
_warm_http(); del _warm_http
import requests as _req; _req.Session(); del _req
```

### 7. Never use faulthandler.enable() in production
`faulthandler` on Windows uses `AddVectoredExceptionHandler` and catches **all** SEH exceptions — including Python 3.13's own internal exception-propagation code `0xe24c4a02`. Every normal network error (timeout, connection reset) in a background thread appears as a fatal crash, and faulthandler's own stack-walk triggers a secondary access violation. faulthandler is useful only as a short-term diagnostic for real segfaults; remove it when done.

## Commands
- `uv run .\main.py` — launch the GUI
- `uv run pytest` — run tests

## Setup
```
cp .env.example .env   # fill in SUBSONIC_SERVER_URL, SUBSONIC_USERNAME, SUBSONIC_PASSWORD
uv sync
```

---

## Architecture

### Dependency Rule
```
domain      →  nothing outside stdlib
repository  →  domain.ports only
controller  →  domain.ports only
services    →  domain + repository + controller  (composition root — wires concretions)
ui          →  services, domain.ports, queue, image_store
```
Never import a concrete repository or backend class outside of `services.py`.

### Layer Decomposition

```
Domain        domain/track.py               Track frozen dataclass + from_subsonic() factory
              domain/ports.py               AudioPort, StreamPort, MusicLibraryPort (Protocols)
              domain/audio_player.py        MpvAudioBackend — implements AudioPort via libmpv

Repository    repository/_http.py           SubsonicHttp — token auth + HTTP transport (internal only)
              repository/music_repository.py SubsonicMusicRepository — implements both ports
              repository/subsonic_client.py  SubsonicClient = SubsonicMusicRepository (compat alias)

Controller    controller/playback_controller.py  PlaybackController(audio: AudioPort, stream: StreamPort)

Composition   services.py                   get_repository(), get_audio_backend(), get_playback_controller()

Persistence   queue.py                      PlayQueue — JSON queue at ~/.music-player/queue.json
              image_store.py                In-memory dict + SQLite at ~/.music-player/image_cache.db
              image_cache.py                SQLite CRUD (used by image_store only, not directly)

Interface     ui/app.py                     MusicPlayerWindow — QStackedWidget + sidebar nav
              ui/loading_screen.py          LoadingScreen — StartupCacheWorker progress display
              ui/components/                Pages + shared widgets (see UI Files below)
              ui/workers/                   QThread workers (one network call each)
```

---

### Core Files
| File | Purpose |
|------|---------|
| `domain/track.py` | `Track(id, title, artist, album, duration, track_number, cover_art_id)` — frozen; `Track.from_subsonic(dict)` factory |
| `domain/ports.py` | `AudioPort`, `StreamPort`, `MusicLibraryPort` — `@runtime_checkable` Protocol definitions |
| `domain/audio_player.py` | `MpvAudioBackend` — implements `AudioPort`; `AudioPlayer = MpvAudioBackend` alias |
| `repository/_http.py` | `SubsonicHttp` — token auth (`md5(password+salt)`), `get()`, `get_bytes()`, `stream_url()` |
| `repository/music_repository.py` | `SubsonicMusicRepository` — all Subsonic API calls; implements `MusicLibraryPort` + `StreamPort` |
| `repository/subsonic_client.py` | `SubsonicClient = SubsonicMusicRepository` — backward-compat shim for workers |
| `controller/playback_controller.py` | `PlaybackController(audio, stream)` — inject-only, no concrete imports |
| `services.py` | Composition root — creates and wires `MpvAudioBackend` + `SubsonicMusicRepository` → `PlaybackController` |
| `queue.py` | `PlayQueue` — tracks as plain dicts (id, title, artist, album, duration, coverArt); `get_queue()` singleton |
| `image_store.py` | Module-level memory store: `preload()`, `put()`, `get()`, `get_decoded()`, `decode_artist_images()`, `set_artists()`, `get_artists()` |
| `image_cache.py` | `ImageCache` — SQLite CRUD wrapper; only used by `image_store` |
| `logging.py` | `get_logger(__name__)` — file + console output to `./logs/music_player.log` |

### UI Files
| File | Purpose |
|------|---------|
| `ui/app.py` | `MusicPlayerWindow` — `QStackedWidget` page nav + sidebar; layout and wiring only |
| `ui/loading_screen.py` | `LoadingScreen` — full-window splash; drives `StartupCacheWorker`; emits `ready()` |
| `ui/components/player_bar.py` | `PlayerBar` (80 px, 2-row): row 1 = art + info + transport + volume; row 2 = teal progress bar |
| `ui/components/playback_bridge.py` | `PlaybackBridge` (QObject singleton) — 500 ms poll, queue advance on EOF, all playback signals |
| `ui/components/track_table.py` | `TrackTable` — shared track listing; double-click plays, right-click context menu; expands to full row count |
| `ui/components/flow_grid.py` | `FlowGrid` — responsive `QGridLayout` wrapper; re-columns on `resizeEvent` |
| `ui/components/artists_page.py` | `ArtistsPage` — internal stack: artist grid (`FlowGrid`) ↔ artist detail |
| `ui/components/artist_card.py` | `ArtistCard` (190×220) — 150 px circle image; `set_pixmap(QPixmap)` for pre-decoded images |
| `ui/components/artist_detail_page.py` | Artist hero + ListenBrainz top 10 + discography (`FlowGrid`) + album track panel (`TrackTable`) |
| `ui/components/musicbrainz_image.py` | `fetch_artist_image_bytes(name)` — Deezer first, iTunes fallback; no caching (caller's responsibility) |

### Worker Threads
| File | Class(es) | Notes |
|------|-----------|-------|
| `ui/workers/startup_cache.py` | `StartupCacheWorker` | Preload SQLite → fetch artists+albums in parallel → parallel image fetch (16 threads) → `decode_artist_images()` |
| `ui/workers/artist_worker.py` | `ArtistListWorker` | `getArtists` → emits `list[dict]`; used as fallback if store is empty |
| `ui/workers/artist_detail.py` | `LoadArtistAlbumsWorker`, `LoadTopTracksWorker` | Albums newest-first; top tracks via MusicBrainz MBID → ListenBrainz |
| `ui/workers/album_tracks.py` | `LoadAlbumTracksWorker` | `getAlbum(id)` → emits `(list[dict], album_dict)` |
| `ui/workers/image_loader.py` | `ImageQueueWorker` | Cache-first; Deezer/iTunes fallback; 8 parallel threads |

---

## Data Flow

### Startup
1. `main.py` shows `LoadingScreen`
2. `StartupCacheWorker` runs:
   - `image_store.preload()` — bulk-reads SQLite into RAM
   - `get_artists()` + `get_all_albums()` fetched in parallel
   - `image_store.set_artists(artists)` stores list for instant tab render
   - Missing artist images fetched via Deezer/iTunes; missing album covers via `getCoverArt` — all in one 16-thread pool
   - `image_store.decode_artist_images()` — decodes all artist bytes to circle-clipped `QImage` (8 threads, runs every startup)
3. `LoadingScreen` emits `ready()` → main window shows

### Artists Tab
- First open: `ensure_loaded()` reads `image_store.get_artists()` (already in RAM)
- Cards rendered in batches of 50 via `QTimer.singleShot(0, ...)` — UI stays responsive
- Each card: `image_store.get_decoded(f"artist:{name.lower()}")` → `QPixmap.fromImage()` — no decode on main thread
- Artist click → `LoadArtistAlbumsWorker` + `LoadTopTracksWorker` fire concurrently
- Album click → `LoadAlbumTracksWorker` → `TrackTable` appears below discography
- Revisiting the tab: stack index flip only — no reload

### Playback
- Double-click track in `TrackTable` → `queue.set_queue(all_tracks, row)` → `bridge.play_track(track)`
- `PlaybackBridge` → `PlaybackController.play_track(id)` → `SubsonicMusicRepository.get_stream_url(id)` → `MpvAudioBackend.play(url)`
- `PlaybackBridge` polls every 500 ms: emits `position_changed` → `PlayerBar` updates slider/timestamps
- EOF detected → `queue.advance()` → next track plays automatically
- Queue persisted to `~/.music-player/queue.json` on every mutation; restored on next launch (no auto-play)

### Image Cache Keys
| Prefix | Source | Populated by |
|--------|--------|--------------|
| `artist:{name_lower}` | Deezer / iTunes | `StartupCacheWorker` |
| `album:{coverArt_id}` | Subsonic `getCoverArt` | `StartupCacheWorker` |

---

## SubsonicMusicRepository Methods
| Method | Endpoint | Notes |
|--------|----------|-------|
| `get_stream_url(id)` | `stream.view` | Session-scoped URL with auth tokens; never cache |
| `get_artists()` | `getArtists` | Flattens A-Z index grouping |
| `get_artist(id)` | `getArtist` | Returns dict with `album: [...]` list |
| `get_album(id)` | `getAlbum` | Returns dict with `song: [...]` list |
| `get_all_albums()` | `getAlbumList2` | Paginated internally (500/page) |
| `get_cover_art(id, size)` | `getCoverArt` | Accepts song, album, or artist ID; 404 → `httpx.HTTPStatusError` |
| `ping()` | `ping.view` | Returns bool; used for health check |

## OpenSubsonic Auth
Token-based per-request: `t = md5(password + salt)`, `s = secrets.token_hex(8)`.
All requests include `?u=&t=&s=&v=1.16.1&c=music-player&f=json`.
Implemented in `SubsonicHttp._auth_params()` — never duplicated elsewhere.

---

## Track Dataclass (`domain/track.py`)
```python
@dataclass(frozen=True)
class Track:
    id: str
    title: str
    artist: str
    album: str
    duration: int          # seconds
    track_number: int | None = None
    cover_art_id: str = ""
```
- `stream_url` is **not stored** — rebuilt fresh each play via `StreamPort.get_stream_url(id)`
- Use `Track.from_subsonic(song_dict)` to construct from API responses
- Workers and `TrackTable` currently use raw `dict` from Subsonic; convert with `Track.from_subsonic()` when domain logic is needed

## Queue Track Format
`PlayQueue` stores plain dicts (not `Track` objects) to simplify JSON serialization:
```python
{"id": str, "title": str, "artist": str, "album": str, "duration": int, "coverArt": str}
```
`_strip()` in `queue.py` enforces these fields; `stream_url` is never persisted.

---

## Glyphs — no emoji in the UI

- **Never use emoji (U+1F000+ range) in any UI string.**  Emoji render as coloured images on Windows 11 and look out of place in a dark desktop app.
- **Never use ambiguous Unicode symbols** that emoji fonts intercept: ▶ (U+25B6), ⏭ (U+23ED), ☁ (U+2601), ♡ (U+2661), ☰ (U+2630), 🔊, etc.
- **Always import from `src.music_player.ui.glyphs`** — that module is the single source of all UI symbols.  All constants are Segoe MDL2 Assets code points (U+E000–U+F8FF, Private Use Area) which are never intercepted by emoji fonts.
- **Apply `font-family` with MDL2 first** on any widget that mixes glyphs and Latin text (menus, list items): use `MDL2_FAMILY_CSS` from `glyphs.py` in the stylesheet so Qt's per-character fallback picks glyphs from MDL2 and letters from Segoe UI.
- **Buttons that show only a glyph** (transport controls, icon buttons) must have `QFont(MDL2_FONT, size)` set explicitly via `_mdl2(size)`.

```python
# correct
from src.music_player.ui.glyphs import PLAY, NEXT, SEARCH, MDL2_FONT, MDL2_FAMILY_CSS
menu.addAction(f"{SEARCH}  Find…")
btn.setFont(QFont(MDL2_FONT, 12))

# wrong — emoji or ambiguous symbol
menu.addAction("🔍  Find…")
btn.setText("▶")
```

## Conventions

- **All imports use the `src.music_player` prefix** — package runs from source (not installed).
- **`logger = get_logger(__name__)` at the top of every module** — add it without asking if missing.
- **`pyqtSlot` must be imported at module level** in any file that uses `@pyqtSlot`. Missing it causes a `NameError` at class definition time. Always include it in the `from PyQt6.QtCore import ...` line, e.g. `from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot`. Never import it inside a method body.
- PyQt6 only — never PyQt5 or PySide6.
- HTTP calls in `QThread.run()` only — never block the main thread.
- Full type hints on all public functions and methods.
- No `print()` — use `logger.*` or a status label.
- No hardcoded colors — the player bar uses `#2dd4bf` (teal) as accent; define as a module constant, not inline.
- `image_store` is the single source of truth for images after startup — never open `ImageCache` directly in UI code.
- `get_bridge()` is the single entry point for all playback operations from UI — never import `PlaybackController` in UI components.

## Consistency & Reuse

- **Never duplicate logic** — one canonical implementation per operation.
- `TrackTable` is the only track listing component — never build a custom one.
- `FlowGrid` is the only responsive grid component — use it for any card grid.
- `SubsonicMusicRepository` is the only Subsonic data access class — workers import `SubsonicClient` (alias).
- Workers emit raw Subsonic dicts — callers use `Track.from_subsonic()` when they need domain objects.
- Any change visible in one tab must be applied consistently across all tabs.

## Known Anti-Patterns to Avoid

- **Importing concrete classes across layer boundaries** — `PlaybackController` must never import `MpvAudioBackend` or `SubsonicMusicRepository`.
- **Opening `ImageCache` in UI code** — use `image_store.get()` / `image_store.put()` only.
- **Spawning one thread per card** — use `ImageQueueWorker` (pooled) or `StartupCacheWorker` (startup batch).
- **Fixed column grids** — use `FlowGrid` so layouts adapt to window width.
- **`set_image(bytes)` on the main thread for bulk rendering** — pre-decode with `image_store.decode_artist_images()` and use `set_pixmap(QPixmap.fromImage(...))` instead.
- **Calling `QApplication.processEvents()`** — use `QTimer.singleShot(0, ...)` batch rendering instead.
