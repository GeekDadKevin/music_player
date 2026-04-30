"""Single process-wide playback bridge.

Access via get_bridge() — never instantiate PlaybackBridge directly.
All UI components that need playback state connect to this object's signals.

Download-retry logic
--------------------
Octofiesta downloads external songs on first stream access, so the initial
request may return immediately with no data (fast EOF).  Two mechanisms
handle this:

  1. EOF grace period — we suppress any eof_reached signal for _EOF_GRACE_S
     seconds after every play_track() call.  This prevents the poll timer
     from mistaking the transient post-play eof_reached=True for a real end.

  2. Download-retry loop — if eof_reached fires within _FAST_EOF_S seconds of
     playback starting, we treat it as "download not ready yet" and reschedule
     the same track after _RETRY_DELAY_S seconds, up to _MAX_RETRIES times.
     A status_message signal keeps the UI informed.
"""

import time

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from src.music_player.logging import get_logger
from src.music_player.queue import get_queue
from src.music_player.services import get_playback_controller

logger = get_logger(__name__)

_POLL_MS      = 500    # polling interval
_EOF_GRACE_S  = 1.5    # suppress EOF for this long after every play_track()
_FAST_EOF_S   = 2.0    # EOF within this many seconds → download not ready
_RETRY_DELAY_S = 4     # wait this long before retrying a not-ready track
_MAX_RETRIES  = 15     # give up after ~60 s of waiting


class PlaybackBridge(QObject):
    # ── signals ───────────────────────────────────────────────────────
    track_changed          = pyqtSignal(dict)         # new track started
    position_changed       = pyqtSignal(float, float) # time_pos, duration
    playback_state_changed = pyqtSignal(bool)         # is_playing
    status_message         = pyqtSignal(str)          # e.g. "Downloading… (2/15)"
    star_state_changed     = pyqtSignal(bool)         # True = current track is starred
    queue_changed          = pyqtSignal()             # queue mutated (add/remove/reorder)

    def __init__(self) -> None:
        super().__init__()
        self._controller = get_playback_controller()

        # EOF state
        self._eof_seen         = False
        self._eof_ignore_until = 0.0
        self._play_start_time  = 0.0

        # Retry state
        self._retry_track: dict | None = None
        self._retry_count = 0

        # Play-count tracking
        self._current_track:   dict | None = None
        self._play_counted     = False

        # Starred-track state (loaded once, updated on toggle)
        self._starred_ids: set[str] = set()
        self._star_workers: list = []
        QTimer.singleShot(2000, self._load_starred_ids)

        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

        # Restore saved track label on startup (no auto-play)
        saved = get_queue().current()
        if saved:
            self.track_changed.emit(saved)

    # ── playback API ──────────────────────────────────────────────────

    def play_track(self, track: dict) -> None:
        """Start streaming a track immediately, resetting all retry state."""
        self._eof_seen         = False
        self._eof_ignore_until = time.monotonic() + _EOF_GRACE_S
        self._play_start_time  = time.monotonic()
        self._retry_track      = None
        self._retry_count      = 0
        self.status_message.emit("")

        self._current_track = track
        self._play_counted  = False
        self._controller.play_track(track["id"])
        self.track_changed.emit(track)
        self.playback_state_changed.emit(True)
        self.star_state_changed.emit(track.get("id", "") in self._starred_ids)
        logger.info(f"play_track: {track.get('title')!r}")

    def play_pause(self) -> None:
        if self._current_track is None:
            # Nothing loaded yet — start playing the current queue item
            current = get_queue().current()
            if current:
                self.play_track(current)
            return
        self._controller.pause()
        self.playback_state_changed.emit(self._controller.is_playing)

    def next_track(self) -> None:
        nxt = get_queue().advance()
        if nxt:
            self.play_track(nxt)

    def previous_track(self) -> None:
        if self._controller.time_pos > 3:
            self._controller.seek(0)
        else:
            prev = get_queue().go_back()
            if prev:
                self.play_track(prev)

    def stop(self) -> None:
        self._retry_track = None
        self._retry_count = 0
        self.status_message.emit("")
        self._controller.stop()
        self.playback_state_changed.emit(False)

    def seek(self, seconds: float) -> None:
        self._controller.seek(seconds)

    def set_volume(self, volume: int) -> None:
        self._controller.set_volume(volume)

    # ── polling ───────────────────────────────────────────────────────

    def _poll(self) -> None:
        try:
            time_pos = self._controller.time_pos
            duration = self._controller.duration
            self.position_changed.emit(time_pos, duration)

            # Record play once threshold is crossed (once per track)
            if not self._play_counted and self._current_track and time_pos > 0:
                self._maybe_record_play(time_pos)

            eof = self._controller.eof_reached
            if eof and not self._eof_seen:
                if time.monotonic() < self._eof_ignore_until:
                    return
                self._eof_seen = True
                self._on_track_ended()
            elif not eof:
                self._eof_seen = False

        except Exception as exc:
            logger.debug(f"poll error: {exc}")

    def _maybe_record_play(self, time_pos: float) -> None:
        from src.music_player.ui.app_settings import load_settings
        from src.music_player.repository.play_history_db import record_play
        threshold = load_settings().min_play_seconds
        if time_pos >= threshold:
            self._play_counted = True
            record_play(self._current_track, int(time_pos))

    # ── starred / heart ───────────────────────────────────────────────

    def _load_starred_ids(self) -> None:
        """Load the set of starred song IDs in the background on startup."""
        from src.music_player.ui.workers.starred import LoadStarredWorker
        w = LoadStarredWorker(parent=self)
        w.songs_loaded.connect(self._on_starred_loaded)
        self._star_workers.append(w)
        w.start()

    def _on_starred_loaded(self, songs: list) -> None:
        self._starred_ids = {s.get("id", "") for s in songs if s.get("id")}
        # Refresh state for current track if one is playing
        if self._current_track:
            tid = self._current_track.get("id", "")
            self.star_state_changed.emit(tid in self._starred_ids)

    def is_starred(self, song_id: str) -> bool:
        return song_id in self._starred_ids

    def toggle_star_current(self) -> None:
        """Toggle the star state of the currently playing track."""
        if not self._current_track:
            return
        song_id = self._current_track.get("id", "")
        if not song_id:
            return
        new_state = song_id not in self._starred_ids
        # Optimistic update
        if new_state:
            self._starred_ids.add(song_id)
        else:
            self._starred_ids.discard(song_id)
        self.star_state_changed.emit(new_state)
        # Persist to server
        from src.music_player.ui.workers.starred import StarToggleWorker
        w = StarToggleWorker(song_id, new_state, parent=self)
        w.failed.connect(lambda msg: self._revert_star(song_id, new_state, msg))
        self._star_workers.append(w)
        w.start()

    def _revert_star(self, song_id: str, failed_state: bool, msg: str) -> None:
        """Roll back optimistic update if server call failed."""
        logger.warning(f"Star toggle failed ({song_id}): {msg} — reverting")
        if failed_state:
            self._starred_ids.discard(song_id)
        else:
            self._starred_ids.add(song_id)
        if self._current_track and self._current_track.get("id") == song_id:
            self.star_state_changed.emit(not failed_state)

    # ── internal ──────────────────────────────────────────────────────

    def _on_track_ended(self) -> None:
        elapsed = time.monotonic() - self._play_start_time

        if elapsed < _FAST_EOF_S:
            # Download not ready — schedule a retry for the same track
            current = get_queue().current()
            if current and self._retry_count < _MAX_RETRIES:
                self._retry_count += 1
                self._retry_track = current
                msg = f"Downloading… ({self._retry_count}/{_MAX_RETRIES})"
                self.status_message.emit(msg)
                logger.info(
                    f"Stream not ready for {current.get('title')!r} "
                    f"— retry {self._retry_count}/{_MAX_RETRIES} "
                    f"in {_RETRY_DELAY_S}s"
                )
                QTimer.singleShot(int(_RETRY_DELAY_S * 1000), self._retry_play)
                return

            # Retries exhausted — give up and advance
            logger.warning(
                f"Giving up on {(self._retry_track or {}).get('title')!r} "
                f"after {_MAX_RETRIES} retries"
            )

        # Normal track end (or gave up) — advance queue
        self.status_message.emit("")
        self._retry_track = None
        self._retry_count = 0

        nxt = get_queue().advance()
        if nxt:
            self.play_track(nxt)
        else:
            self.playback_state_changed.emit(False)

    def _retry_play(self) -> None:
        track = self._retry_track
        if not track:
            return

        # Reset EOF gate so the retry attempt gets a clean slate
        self._eof_seen         = False
        self._eof_ignore_until = time.monotonic() + _EOF_GRACE_S
        self._play_start_time  = time.monotonic()

        try:
            self._controller.play_track(track["id"])
            logger.debug(f"Retry play: {track.get('title')!r}")
        except Exception as exc:
            logger.warning(f"Retry play_track failed: {exc}")


# ── singleton ─────────────────────────────────────────────────────────

_bridge: PlaybackBridge | None = None


def get_bridge() -> PlaybackBridge:
    """Return the process-wide PlaybackBridge, creating it if needed."""
    global _bridge
    if _bridge is None:
        _bridge = PlaybackBridge()
    return _bridge
