"""Application-layer controller for audio playback.

Depends ONLY on domain.ports abstractions — never on concrete repository
or audio-backend classes.  This enforces the dependency inversion principle:
high-level policy (the controller) does not depend on low-level details
(mpv, Subsonic HTTP).

Wiring is done externally in services.py (the composition root).

Contract:
- play_track() is idempotent with respect to the audio backend: calling it
  again immediately stops the current track and starts the new one.
- The controller holds no queue state; queue management is the caller's
  responsibility (PlaybackBridge + PlayQueue).
- All property reads are safe when nothing is playing; they return 0.0 or
  False rather than raising.
- This class is not thread-safe.  All methods must be called from the Qt
  main thread (via PlaybackBridge slots).
"""

from __future__ import annotations

from src.music_player.domain.ports import AudioPort, StreamPort
from src.music_player.logging import get_logger

logger = get_logger(__name__)


class PlaybackController:
    """Orchestrates a StreamPort and an AudioPort to play music.

    Knows nothing about mpv, Subsonic, or any concrete class.
    Receives its dependencies via constructor injection.
    """

    def __init__(self, audio: AudioPort, stream: StreamPort) -> None:
        """
        Args:
            audio:  AudioPort implementation (e.g. MpvAudioBackend).
            stream: StreamPort implementation (e.g. SubsonicMusicRepository).

        Assumption: both dependencies are already initialised and ready;
        this constructor performs no I/O.
        """
        self._audio = audio
        self._stream = stream
        self._current_track_id: str | None = None

    # ── playback commands ─────────────────────────────────────────────

    def play_track(self, track_id: str) -> None:
        """Resolve track_id to a stream URL and begin playback.

        Any currently playing track is stopped before the new one starts.

        Raises:
        - StreamPort exceptions (httpx.HTTPError, RuntimeError) if the URL
          cannot be resolved.
        """
        url = self._stream.get_stream_url(track_id)
        self._audio.play(url)
        self._current_track_id = track_id
        logger.info(f"play_track: {track_id}")

    def pause(self) -> None:
        """Toggle pause.  No-op if nothing is loaded."""
        self._audio.pause()

    def stop(self) -> None:
        """Stop playback and clear current track ID."""
        self._audio.stop()
        self._current_track_id = None

    def seek(self, seconds: float) -> None:
        """Seek to absolute position in seconds."""
        self._audio.seek(seconds)

    def set_volume(self, volume: int) -> None:
        """Set output volume in [0, 100]."""
        self._audio.set_volume(volume)

    # ── state queries ─────────────────────────────────────────────────

    @property
    def current_track_id(self) -> str | None:
        """The Subsonic song ID of the track currently loaded, or None."""
        return self._current_track_id

    @property
    def is_playing(self) -> bool:
        return self._audio.is_playing

    @property
    def eof_reached(self) -> bool:
        return self._audio.eof_reached

    @property
    def time_pos(self) -> float:
        return self._audio.time_pos

    @property
    def duration(self) -> float:
        return self._audio.duration
