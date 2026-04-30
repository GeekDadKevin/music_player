"""Backward-compatibility shim.

New code should use:
    from src.music_player.repository.music_repository import SubsonicMusicRepository

or, for injected dependencies:
    from src.music_player.services import get_repository

SubsonicClient is kept as an alias so existing worker imports continue to
work without modification.
"""

from src.music_player.repository.music_repository import SubsonicMusicRepository

SubsonicClient = SubsonicMusicRepository

__all__ = ["SubsonicClient", "SubsonicMusicRepository"]
