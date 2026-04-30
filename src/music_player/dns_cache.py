"""Process-wide DNS lookup cache.

Patches socket.getaddrinfo with an LRU cache so repeated calls to the same
hostnames (Navidrome server, MusicBrainz, Deezer, iTunes) skip the OS resolver
after the first lookup.  Safe for a single-process desktop app.

Call install() once at startup before any network I/O.
"""

import functools
import socket

from src.music_player.logging import get_logger

logger = get_logger(__name__)

_installed = False


def install() -> None:
    """Monkey-patch socket.getaddrinfo with a 512-entry LRU cache."""
    global _installed
    if _installed:
        return
    _installed = True

    _orig = socket.getaddrinfo

    @functools.lru_cache(maxsize=512)
    def _cached(host, port, family=0, type=0, proto=0, flags=0):  # noqa: A002
        return _orig(host, port, family, type, proto, flags)

    socket.getaddrinfo = _cached  # type: ignore[assignment]
    logger.info("DNS cache installed (lru_cache maxsize=512)")
