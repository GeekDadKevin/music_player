import re
import time

import requests

from src.music_player.logging import get_logger

logger = get_logger(__name__)

_MB_HEADERS = {"User-Agent": "MusicPlayer/1.0 (kevinloverman@gmail.com)"}

# Simple in-memory cache so re-opening the same album doesn't re-hit MB
_tracklist_cache: dict[str, list[dict]] = {}


def fetch_tracklist(artist: str, album: str) -> list[dict]:
    """Return the canonical track list for an album from MusicBrainz.

    Each dict has: title (str), track_number (int), duration (int, seconds).
    Returns [] on failure or no match.
    Cached in memory and in SQLite so it survives app restarts and offline use.
    """
    cache_key = f"{artist.lower().strip()}|||{album.lower().strip()}"
    if cache_key in _tracklist_cache:
        return _tracklist_cache[cache_key]

    # Check SQLite cache first (works offline after first fetch)
    from src.music_player.repository.track_cache_db import get_cached, set_cached
    db_key = f"mb_tracklist:{cache_key}"
    cached = get_cached(db_key)
    if cached is not None:
        _tracklist_cache[cache_key] = cached
        return cached

    try:
        query = f'release:"{album}" AND artist:"{artist}"'
        resp = requests.get(
            "https://musicbrainz.org/ws/2/release/",
            params={"query": query, "fmt": "json", "limit": 10},
            headers=_MB_HEADERS,
            timeout=10,
        )
        if resp.status_code != 200:
            _tracklist_cache[cache_key] = []
            return []
        releases = resp.json().get("releases", [])
        if not releases:
            _tracklist_cache[cache_key] = []
            return []

        def _rank(r: dict) -> tuple:
            return (
                1 if r.get("status") == "Official" else 0,
                1 if r.get("release-group", {}).get("primary-type") == "Album" else 0,
                r.get("score", 0),
            )
        releases.sort(key=_rank, reverse=True)
        mbid = releases[0].get("id", "")
        if not mbid:
            _tracklist_cache[cache_key] = []
            return []

        time.sleep(1.1)  # respect MB rate limit (1 req/sec)
        detail = requests.get(
            f"https://musicbrainz.org/ws/2/release/{mbid}",
            params={"inc": "recordings", "fmt": "json"},
            headers=_MB_HEADERS,
            timeout=10,
        )
        if detail.status_code != 200:
            _tracklist_cache[cache_key] = []
            return []

        tracks: list[dict] = []
        for medium in detail.json().get("media", []):
            for t in medium.get("tracks", []):
                rec  = t.get("recording", {})
                ms   = t.get("length") or rec.get("length") or 0
                tracks.append({
                    "title":        t.get("title") or rec.get("title", ""),
                    "track_number": t.get("position", 0),
                    "duration":     int(ms / 1000),
                })
        _tracklist_cache[cache_key] = tracks
        set_cached(db_key, tracks)   # persist for offline use
        logger.debug(f"MB tracklist: {len(tracks)} tracks for {artist!r} - {album!r}")
        return tracks

    except Exception as exc:
        logger.debug(f"MB tracklist failed ({artist} - {album}): {exc}")
        _tracklist_cache[cache_key] = []
        return []


def _normalize_title(title: str) -> str:
    """Lowercase + strip common suffixes so 'Track (Explicit)' matches 'Track'."""
    t = title.lower().strip()
    t = re.sub(r"\s*[\(\[]?(feat|ft|featuring)\.?\s+[^\)\]]*[\)\]]?", "", t)
    t = re.sub(
        r"\s*[\(\[].*?(remaster(?:ed)?|deluxe|edition|version|explicit|clean|radio.edit).*?[\)\]]",
        "", t, flags=re.IGNORECASE,
    )
    return t.strip()


def fetch_artist_image_bytes(artist_name: str) -> bytes:
    """Fetch artist image bytes with no caching. Priority: Deezer → iTunes → empty."""
    data = _try_deezer(artist_name)
    if data:
        return data
    data = _try_itunes(artist_name)
    return data


def fetch_album_cover_bytes(artist: str, album: str) -> bytes:
    """Fetch album cover art. Priority: MusicBrainz CAA → Deezer → empty."""
    data = _try_musicbrainz_album(artist, album)
    if data:
        return data
    return _deezer_album_cover(artist, album)


def _try_musicbrainz_album(artist: str, album: str) -> bytes:
    """Search MusicBrainz and fetch cover from Cover Art Archive."""
    try:
        query = f'release:"{album}" AND artist:"{artist}"'
        resp = requests.get(
            "https://musicbrainz.org/ws/2/release/",
            params={"query": query, "fmt": "json", "limit": 5},
            headers=_MB_HEADERS,
            timeout=10,
        )
        if resp.status_code != 200:
            return b""
        releases = resp.json().get("releases", [])
        for release in releases:
            mbid = release.get("id", "")
            if not mbid:
                continue
            img = requests.get(
                f"https://coverartarchive.org/release/{mbid}/front-500",
                headers=_MB_HEADERS,
                timeout=10,
                allow_redirects=True,
            )
            if img.status_code == 200 and img.content:
                logger.debug(f"MusicBrainz CAA hit for {artist!r} - {album!r} ({mbid})")
                return img.content
    except Exception as exc:
        logger.debug(f"MusicBrainz album cover failed ({artist} - {album}): {exc}")
    return b""


def _deezer_album_cover(artist: str, album: str) -> bytes:
    query = f"{artist} {album}".strip()
    if not query:
        return b""
    try:
        resp = requests.get(
            "https://api.deezer.com/search/album",
            params={"q": query, "limit": 1},
            timeout=8,
        )
        if resp.status_code == 200:
            items = resp.json().get("data", [])
            if items:
                url = items[0].get("cover_big") or items[0].get("cover_medium")
                if url:
                    img = requests.get(url, timeout=8)
                    if img.status_code == 200:
                        return img.content
    except Exception as exc:
        logger.debug(f"Deezer album cover failed ({artist} - {album}): {exc}")
    return b""


def _try_deezer(artist_name: str) -> bytes:
    try:
        search = requests.get(
            "https://api.deezer.com/search/artist",
            params={"q": artist_name, "limit": 1},
            timeout=8,
        )
        if search.status_code == 200:
            results = search.json().get("data", [])
            if results:
                img_url = results[0].get("picture_xl") or results[0].get("picture_big")
                if img_url:
                    img = requests.get(img_url, timeout=8)
                    if img.status_code == 200:
                        return img.content
    except Exception as exc:
        logger.debug(f"Deezer failed for {artist_name!r}: {exc}")
    return b""


def _try_itunes(artist_name: str) -> bytes:
    try:
        search = requests.get(
            "https://itunes.apple.com/search",
            params={"term": artist_name, "entity": "musicArtist", "limit": 1},
            timeout=8,
        )
        if search.status_code == 200:
            results = search.json().get("results", [])
            if results:
                url = results[0].get("artworkUrl100", "")
                if url:
                    url = url.replace("100x100bb", "600x600bb")
                    img = requests.get(url, timeout=8)
                    if img.status_code == 200:
                        return img.content
    except Exception as exc:
        logger.debug(f"iTunes failed for {artist_name!r}: {exc}")
    return b""
