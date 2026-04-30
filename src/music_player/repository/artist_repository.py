"""Deprecated — absorbed into SubsonicMusicRepository.

ArtistRepository duplicated the auth logic that now lives in SubsonicHttp
and is no longer called by any module.  It is kept only to avoid import
errors in case of stale .pyc files; it will be removed in a future cleanup.

Use instead:
    from src.music_player.repository.music_repository import SubsonicMusicRepository
    repo = SubsonicMusicRepository()
    artists = repo.get_artists()
    artist  = repo.get_artist(artist_id)
"""

from src.music_player.repository.music_repository import SubsonicMusicRepository as _R


class ArtistRepository:
    """Deprecated wrapper kept for backward compatibility only."""

    def __init__(self, server_url: str, username: str, password: str) -> None:
        self._inner = _R()

    def get_artists(self) -> list[dict]:
        return self._inner.get_artists()

    def get_artist(self, artist_id: str) -> dict | None:
        return self._inner.get_artist(artist_id)
