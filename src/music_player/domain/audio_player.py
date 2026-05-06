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
from src.music_player._paths import app_root as _app_root
_lib_dir = str(_app_root() / "lib" / "mpv")
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
        # audio-only: disable video/window/input to avoid Win32 hook conflicts.
        # start_event_thread=False: defer the mpv event thread so it is NOT
        # running during Qt's window.show().  Qt's native window initialisation
        # (HWND creation, OpenGL context setup) triggers Python's cyclic GC,
        # which in Python 3.13 finalises objects with __del__ that are in
        # reference cycles.  MPV has internal cycles (_stream_protocol_cbs ->
        # bound-method -> MPV); when GC finalises MPV it calls
        # _mpv_terminate_destroy while the event thread is blocked in
        # _mpv_wait_event, causing an access violation.  By deferring the
        # thread start until after window.show() the event thread is never
        # live during the dangerous window.  Call start_event_thread() once
        # the Qt window is fully shown.
        self._player = mpv.MPV(
            ytdl=True,
            video=False,                    # no video output, no VO window
            input_default_bindings=False,   # no global keyboard shortcuts
            input_vo_keyboard=False,        # no keyboard capture from VO
            start_event_thread=False,       # started manually after window.show()
        )
        logger.info("MpvAudioBackend initialised (event thread deferred)")

    def start_event_thread(self) -> None:
        """Start the mpv event-processing thread.

        Must be called once, after Qt's window.show() completes.  The thread
        is created with the same parameters that python-mpv would use when
        start_event_thread=True so that __del__ / terminate() still join it
        correctly.
        """
        if self._player._event_thread is not None:
            logger.warning("MpvAudioBackend: start_event_thread called twice — ignored")
            return
        t = threading.Thread(
            target=self._player._loop,
            name="MPVEventHandlerThread",
            daemon=True,
        )
        self._player._event_thread = t
        t.start()
        logger.info("MpvAudioBackend: event thread started")

    # ── AudioPort implementation ──────────────────────────────────────

    def play(self, url: str) -> None:
        """Begin streaming url.  Stops any currently playing media first."""
        self._player.play(url)

    def pause(self) -> None:
        """Toggle pause state."""
        self._player.pause = not self._player.pause

    def stop(self) -> None:
        """Stop playback and unload current media."""
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
        return bool(self._player.idle_active)

    def set_audio_device(self, speaker_id: str) -> None:
        """Route mpv audio output to the speaker identified by speaker_id.

        Args:
            speaker_id: The ``soundcard`` speaker ``.id`` string.  An empty
                string resets mpv to the system default (``auto``).
        """
        try:
            if not speaker_id:
                self._player.audio_device = "auto"
                logger.info("MpvAudioBackend: audio device reset to auto (system default)")
                return
            import soundcard as sc
            match = next((s for s in sc.all_speakers() if s.id == speaker_id), None)
            if match is None:
                logger.warning(
                    f"MpvAudioBackend: speaker id {speaker_id!r} not found — "
                    "falling back to auto"
                )
                self._player.audio_device = "auto"
                return
            self._player.audio_device = f"wasapi/{match.name}"
            logger.info(
                f"MpvAudioBackend: audio device set to wasapi/{match.name!r}"
            )
        except Exception as exc:
            logger.warning(
                f"MpvAudioBackend: set_audio_device failed ({exc}) — "
                "falling back to auto"
            )
            try:
                self._player.audio_device = "auto"
            except Exception:
                pass


# Backward-compatibility alias so any code that imported AudioPlayer still works.
AudioPlayer = MpvAudioBackend
