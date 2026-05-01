"""mpv-based audio backend — the concrete implementation of AudioPort.

This module is infrastructure masquerading as domain by file location.
It is referenced only by services.py (the composition root); nothing in the
controller or domain layers imports it directly.

Assumptions:
- mpv (libmpv) is installed and findable on PATH.  On Windows the DLL is
  expected in lib/mpv/ relative to the project root; the PATH manipulation
  below handles that without requiring a system-wide install.
- A QApplication (or QCoreApplication) is already running when an instance
  is created, because MpvAudioBackend is created inside PlaybackBridge which
  is itself created lazily after QApplication.exec() starts.
- ytdl=True has no effect when playing direct HTTP URLs; it is left enabled
  so that mpv can handle non-HTTP schemes if ever needed.
"""

from __future__ import annotations

import os
import threading

from src.music_player.logging import get_logger

# Windows: libmpv-2.dll lives in lib/mpv/ — prepend it to PATH before
# importing the binding so ctypes finds it without a system install.
_lib_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib", "mpv")
)
os.environ["PATH"] = _lib_dir + os.pathsep + os.environ.get("PATH", "")

import mpv  # noqa: E402

logger = get_logger(__name__)


class MpvAudioBackend:
    """AudioPort implementation backed by libmpv.

    Satisfies AudioPort structurally — no explicit inheritance required.

    Thread safety:
    - mpv property reads (time_pos, duration, eof_reached) are thread-safe.
    - play / stop / seek must be called from a single thread; in practice
      this is the Qt main thread via PlaybackController.
    """

    def __init__(self) -> None:
        # Set before creating the player so the observer can reference it.
        self._eof_event = threading.Event()

        self._player = mpv.MPV(
            ytdl=True,
            input_default_bindings=True,
            input_vo_keyboard=True,
        )

        # idle-active becomes True when mpv has finished playing (track ended
        # or stop() called) and False when mpv starts loading a new file.
        # We set the event on True and clear it on False so that the brief
        # idle-active=True transition that mpv emits when switching tracks
        # (stopping old → loading new) does NOT leave the event permanently
        # set and cause the queue to spuriously advance after the grace period.
        @self._player.property_observer("idle-active")
        def _on_idle(name: str, value: bool | None) -> None:
            if value:
                self._eof_event.set()
            elif value is False:
                self._eof_event.clear()

        logger.info("MpvAudioBackend initialised")

    # ── AudioPort implementation ──────────────────────────────────────

    def play(self, url: str) -> None:
        """Begin streaming url.  Stops any currently playing media first."""
        self._eof_event.clear()
        self._player.play(url)

    def pause(self) -> None:
        """Toggle pause state."""
        self._player.pause = not self._player.pause

    def stop(self) -> None:
        """Stop playback and unload current media."""
        self._eof_event.clear()
        self._player.stop()

    def set_volume(self, volume: int) -> None:
        """Set output volume in [0, 100]."""
        self._player.volume = max(0, min(100, volume))

    def seek(self, seconds: float) -> None:
        """Seek to absolute position in seconds."""
        self._player.seek(seconds, reference="absolute")

    @property
    def is_playing(self) -> bool:
        return not self._player.pause

    @property
    def time_pos(self) -> float:
        return float(self._player.time_pos or 0.0)

    @property
    def duration(self) -> float:
        return float(self._player.duration or 0.0)

    @property
    def eof_reached(self) -> bool:
        return self._eof_event.is_set()


# Backward-compatibility alias so any code that imported AudioPlayer still works.
AudioPlayer = MpvAudioBackend
