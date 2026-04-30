"""Abstract port definitions for the domain layer.

Ports are the application's boundaries — they define what the domain *needs*
from the outside world without caring how it is provided. Infrastructure
modules (repository, audio backend) satisfy these contracts by implementing
the required methods (structural subtyping — no explicit inheritance needed).

The controller and domain layers import only from this module; they never
import concrete repository or infrastructure classes.

Dependency rule:
    domain  →  (nothing outside stdlib)
    repository  →  domain.ports
    controller  →  domain.ports
    services    →  domain.ports + repository + controller (composition root only)
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AudioPort(Protocol):
    """Contract for an audio playback backend.

    Assumptions:
    - Implementations are single-instance and stateful; only one track
      plays at a time.  play() is fire-and-forget.
    - pause() is a toggle: paused → playing, playing → paused.
    - stop() unloads the current media; subsequent property reads return
      safe defaults (0.0 / False).
    - Volume is an integer in [0, 100].
    - All property reads are non-raising; return 0.0 or False on error.

    Implementors:
    - MpvAudioBackend (domain/audio_player.py)
    """

    def play(self, url: str) -> None:
        """Begin streaming url.  Any current playback stops immediately."""
        ...

    def pause(self) -> None:
        """Toggle pause state."""
        ...

    def stop(self) -> None:
        """Stop playback and unload media."""
        ...

    def seek(self, seconds: float) -> None:
        """Seek to absolute position in seconds.  No-op if nothing is loaded."""
        ...

    def set_volume(self, volume: int) -> None:
        """Set output volume.  Clamp to [0, 100] if out of range."""
        ...

    @property
    def is_playing(self) -> bool:
        """True when media is loaded and not paused."""
        ...

    @property
    def time_pos(self) -> float:
        """Current playback position in seconds.  0.0 if nothing is playing."""
        ...

    @property
    def duration(self) -> float:
        """Total duration of current media in seconds.  0.0 if unknown."""
        ...

    @property
    def eof_reached(self) -> bool:
        """True when the current file has played to its natural end.

        Resets to False as soon as play() is called again.
        """
        ...


@runtime_checkable
class StreamPort(Protocol):
    """Contract for resolving a track ID to a streamable URL.

    Assumptions:
    - The returned URL is valid for the current session only; it embeds
      per-request auth tokens (salt + md5 hash).
    - Callers must NOT cache URLs across process restarts.
    - The URL is a secret; log it only at DEBUG level if at all.

    Raises:
    - httpx.HTTPError on network failure.
    - RuntimeError if the server rejects the request.

    Implementors:
    - SubsonicMusicRepository (repository/music_repository.py)
    """

    def get_stream_url(self, track_id: str) -> str:
        """Return a URL that mpv (or any HTTP client) can stream directly."""
        ...


@runtime_checkable
class MusicLibraryPort(Protocol):
    """Contract for reading music library data from a remote server.

    Assumptions:
    - Return values are raw server dicts.  Callers should use Track.from_subsonic()
      to convert songs to domain objects where appropriate.
    - Pagination is handled internally; callers receive a complete flat list.
    - Methods raise RuntimeError on a non-ok server response and
      httpx.HTTPError on network failure.

    Minimum guaranteed fields per method (others may be present):
    - get_artists()     → each dict: id (str), name (str)
    - get_artist(id)    → dict: id, name, album (list of album dicts)
    - get_album(id)     → dict: id, name, artist, song (list of song dicts)
    - get_all_albums()  → each dict: id, name, artist, coverArt, year
    - get_cover_art()   → raw JPEG/PNG bytes

    Implementors:
    - SubsonicMusicRepository (repository/music_repository.py)
    """

    def get_artists(self) -> list[dict]: ...

    def get_artist(self, artist_id: str) -> dict | None: ...

    def get_album(self, album_id: str) -> dict | None: ...

    def get_all_albums(self) -> list[dict]: ...

    def get_cover_art(self, art_id: str, size: int = 300) -> bytes: ...
