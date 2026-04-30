"""Domain entity representing a single playable track.

This is a pure value object with no external dependencies.

Assumptions:
- id is the Subsonic song ID; stable for the lifetime of the library entry.
- duration is in whole seconds; 0 if the server did not provide it.
- stream_url is intentionally absent — URLs contain session auth tokens and
  must be resolved fresh each play via StreamPort.get_stream_url(id).
- cover_art_id is opaque; pass it to MusicLibraryPort.get_cover_art() to
  retrieve bytes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Track:
    id: str
    title: str
    artist: str
    album: str
    duration: int           # seconds
    track_number: int | None = None
    cover_art_id: str = ""

    @classmethod
    def from_subsonic(cls, song: dict) -> Track:
        """Construct a Track from a raw Subsonic song dict.

        Only this factory knows the Subsonic wire format; all other code
        works with Track objects.
        """
        return cls(
            id=str(song["id"]),
            title=song.get("title") or "Unknown",
            artist=song.get("artist") or "Unknown",
            album=song.get("album") or "",
            duration=int(song.get("duration") or 0),
            track_number=song.get("track"),
            cover_art_id=song.get("coverArt") or "",
        )

    def display_duration(self) -> str:
        """Human-readable M:SS string."""
        m, s = divmod(self.duration, 60)
        return f"{m}:{s:02d}"
