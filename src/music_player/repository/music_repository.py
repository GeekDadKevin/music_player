"""OpenSubsonic implementation of MusicLibraryPort and StreamPort.

This is the single repository class for all library data access and stream
URL resolution.  It satisfies both ports structurally (Python Protocol /
duck typing) without explicit inheritance.

Assumptions:
- Server follows OpenSubsonic spec v1.16.1 (Navidrome ≥ 0.49 is known good).
- Artist index is nested: artists → index[] → artist[].  The nesting is
  flattened before returning.
- get_all_albums() uses getAlbumList2 with type=alphabeticalByName and
  handles pagination internally (500 per page).
- get_cover_art() raises httpx.HTTPStatusError (404) when the server has
  no image for a given ID; callers must handle this.

Dependency:
- Depends only on SubsonicHttp (_http.py) for transport, never on domain
  entities or controller code.
"""

from __future__ import annotations

from src.music_player.logging import get_logger
from src.music_player.repository._http import SubsonicHttp

logger = get_logger(__name__)


class SubsonicMusicRepository:
    """Implements MusicLibraryPort + StreamPort against an OpenSubsonic server.

    Instantiated once by services.py and shared across all workers.
    Constructor accepts an optional SubsonicHttp so tests can inject a fake.
    """

    def __init__(self, http: SubsonicHttp | None = None) -> None:
        self._http = http or SubsonicHttp()

    # ── StreamPort ────────────────────────────────────────────────────

    def get_stream_url(self, track_id: str) -> str:
        """Return a stream URL for track_id.

        Contract: URL is session-scoped and contains auth tokens.
        Never log at INFO or above; never cache across restarts.
        """
        return self._http.stream_url(track_id)

    # ── MusicLibraryPort ──────────────────────────────────────────────

    def get_artists(self) -> list[dict]:
        """Return the full artist index as a flat list.

        Each dict contains at minimum: id (str), name (str).
        The server's alphabetical index grouping is stripped.
        """
        data = self._http.get("getArtists.view", timeout=30.0)
        artists: list[dict] = []
        for group in data.get("artists", {}).get("index", []):
            artists.extend(group.get("artist", []))
        logger.info(f"get_artists: {len(artists)} artists")
        return artists

    def get_artist(self, artist_id: str) -> dict | None:
        """Return artist dict including an 'album' list, or None on error.

        Each album in 'album' contains at minimum: id, name, year, coverArt.
        """
        try:
            data = self._http.get("getArtist.view", {"id": artist_id})
            return data.get("artist")
        except (RuntimeError, Exception) as exc:
            logger.warning(f"get_artist({artist_id}) failed: {exc}")
            return None

    def get_album(self, album_id: str) -> dict | None:
        """Return album dict including a 'song' list, or None on error.

        Each song in 'song' is a Subsonic song dict; use Track.from_subsonic()
        to convert to a domain object.
        """
        try:
            data = self._http.get("getAlbum.view", {"id": album_id})
            return data.get("album")
        except (RuntimeError, Exception) as exc:
            logger.warning(f"get_album({album_id}) failed: {exc}")
            return None

    def get_all_albums(self) -> list[dict]:
        """Return every album via paginated getAlbumList2 (alphabetical).

        Pagination is handled internally; the caller receives one flat list.
        Each dict contains at minimum: id, name, artist, coverArt, year.
        Navidrome's sort can be unstable across pages, so we deduplicate by id.
        """
        raw: list[dict] = []
        offset, page_size = 0, 500
        while True:
            data = self._http.get(
                "getAlbumList2.view",
                {"type": "alphabeticalByName", "size": page_size, "offset": offset},
                timeout=30.0,
            )
            page = data.get("albumList2", {}).get("album", [])
            raw.extend(page)
            if len(page) < page_size:
                break
            offset += len(page)

        # 1. Deduplicate by id (unstable sort can return same album on multiple pages)
        seen: dict[str, dict] = {}
        for album in raw:
            aid = album.get("id")
            if aid and aid not in seen:
                seen[aid] = album
        by_id = list(seen.values())

        # 2. Group by normalised (artist, name) — Navidrome sometimes creates multiple
        #    album entries with different IDs for the same logical album (e.g. partial
        #    imports from different directories).  Merge those into one entry so the
        #    grid shows one card per album.  All IDs are stored in _all_ids so the
        #    track loader can pull songs from every fragment.
        groups: dict[tuple[str, str], list[dict]] = {}
        for album in by_id:
            key = (
                album.get("artist", "").lower().strip(),
                album.get("name",   "").lower().strip(),
            )
            groups.setdefault(key, []).append(album)

        albums: list[dict] = []
        merged_count = 0
        for group in groups.values():
            if len(group) == 1:
                albums.append(group[0])
            else:
                merged_count += 1
                best = max(group, key=lambda a: a.get("songCount", 0))
                merged = dict(best)
                merged["_all_ids"] = [a["id"] for a in group]
                albums.append(merged)

        logger.info(
            f"get_all_albums: {len(raw)} raw → {len(by_id)} unique ids "
            f"→ {len(albums)} albums ({merged_count} merged)"
        )
        return albums

    def get_random_songs(self, count: int = 30) -> list[dict]:
        """Return count random songs from the library."""
        try:
            data = self._http.get("getRandomSongs.view", {"size": count}, timeout=15.0)
            return data.get("randomSongs", {}).get("song", [])
        except Exception as exc:
            logger.warning(f"get_random_songs failed: {exc}")
            return []

    def get_genres(self) -> list[dict]:
        """Return all genres from the server.

        Each dict has at minimum: value (genre name), songCount, albumCount.
        """
        try:
            data = self._http.get("getGenres.view", timeout=20.0)
            return data.get("genres", {}).get("genre", [])
        except Exception as exc:
            logger.warning(f"get_genres failed: {exc}")
            return []

    def get_songs_by_genre(self, genre: str, count: int = 500) -> list[dict]:
        """Return up to count songs tagged with genre (paginated internally)."""
        songs: list[dict] = []
        offset, page_size = 0, 500
        while len(songs) < count:
            try:
                batch = min(count - len(songs), page_size)
                data = self._http.get(
                    "getSongsByGenre.view",
                    {"genre": genre, "count": batch, "offset": offset},
                    timeout=30.0,
                )
                page = data.get("songsByGenre", {}).get("song", [])
                songs.extend(page)
                if len(page) < batch:
                    break
                offset += len(page)
            except Exception as exc:
                logger.warning(f"get_songs_by_genre({genre!r}) failed: {exc}")
                break
        logger.info(f"get_songs_by_genre({genre!r}): {len(songs)} songs")
        return songs

    def get_cover_art(self, art_id: str, size: int = 300) -> bytes:
        """Return raw image bytes for a song, album, or artist cover art ID.

        Raises httpx.HTTPStatusError (typically 404) when no image exists.
        Callers that want graceful degradation should catch that exception.
        """
        return self._http.get_bytes("getCoverArt.view", {"id": art_id, "size": size})

    def get_playlists(self) -> list[dict]:
        """Return all playlists visible to the authenticated user.

        Each dict has at minimum: id (str), name (str), songCount (int).
        """
        data = self._http.get("getPlaylists.view")
        return data.get("playlists", {}).get("playlist", [])

    def get_playlist(self, playlist_id: str) -> dict | None:
        """Return a playlist dict including a 'entry' list of song dicts."""
        try:
            data = self._http.get("getPlaylist.view", {"id": playlist_id})
            return data.get("playlist")
        except Exception as exc:
            logger.warning(f"get_playlist({playlist_id}) failed: {exc}")
            return None

    def search(self, query: str, song_count: int = 20) -> list[dict]:
        """Full-text search returning song dicts only.

        Used for playlist import matching — returns at most song_count results.
        """
        try:
            data = self._http.get("search3.view", {
                "query": query,
                "songCount": song_count,
                "artistCount": 0,
                "albumCount": 0,
            })
            return data.get("searchResult3", {}).get("song", [])
        except Exception as exc:
            logger.warning(f"search({query!r}) failed: {exc}")
            return []

    def search_all(
        self,
        query: str,
        artist_count: int = 5,
        album_count: int = 10,
        song_count: int = 20,
    ) -> dict:
        """Full-text search returning artists, albums, and songs in one call."""
        try:
            data = self._http.get("search3.view", {
                "query":       query,
                "artistCount": artist_count,
                "albumCount":  album_count,
                "songCount":   song_count,
            })
            r = data.get("searchResult3", {})
            return {
                "artists": r.get("artist", []),
                "albums":  r.get("album",  []),
                "tracks":  r.get("song",   []),
            }
        except Exception as exc:
            logger.warning(f"search_all({query!r}) failed: {exc}")
            return {"artists": [], "albums": [], "tracks": []}

    def get_starred_songs(self) -> list[dict]:
        """Return all songs starred (hearted) by the authenticated user.

        Uses getStarred2 which supports ID3 tags.  Each dict is a standard
        Subsonic song dict.  Returns empty list on error.
        """
        try:
            data = self._http.get("getStarred2.view")
            return data.get("starred2", {}).get("song", [])
        except Exception as exc:
            logger.warning(f"get_starred_songs failed: {exc}")
            return []

    def star_song(self, song_id: str) -> bool:
        """Star (heart) a song by ID.  Returns True on success."""
        try:
            self._http.get("star.view", {"id": song_id})
            return True
        except Exception as exc:
            logger.warning(f"star_song({song_id}) failed: {exc}")
            return False

    def unstar_song(self, song_id: str) -> bool:
        """Remove the star from a song by ID.  Returns True on success."""
        try:
            self._http.get("unstar.view", {"id": song_id})
            return True
        except Exception as exc:
            logger.warning(f"unstar_song({song_id}) failed: {exc}")
            return False

    def create_playlist(self, name: str, song_ids: list[str]) -> dict | None:
        """Create a new playlist on the server with the given song IDs.

        Contract: song_ids must all be valid Subsonic song IDs.
        Returns the created playlist dict, or None on failure.
        Subsonic receives multiple songId params which httpx expands from a list.
        """
        try:
            data = self._http.get(
                "createPlaylist.view",
                {"name": name, "songId": song_ids},
            )
            logger.info(f"create_playlist: '{name}' with {len(song_ids)} tracks")
            return data.get("playlist")
        except Exception as exc:
            logger.error(f"create_playlist failed: {exc}")
            return None

    def delete_playlist(self, playlist_id: str) -> bool:
        """Delete a server playlist permanently."""
        try:
            self._http.get("deletePlaylist.view", {"id": playlist_id})
            logger.info(f"delete_playlist({playlist_id!r}): ok")
            return True
        except Exception as exc:
            logger.warning(f"delete_playlist failed: {exc}")
            return False

    def add_songs_to_playlist(self, playlist_id: str, song_ids: list[str]) -> bool:
        """Append songs to an existing server playlist."""
        try:
            self._http.get(
                "updatePlaylist.view",
                {"playlistId": playlist_id, "songIdToAdd": song_ids},
            )
            return True
        except Exception as exc:
            logger.warning(f"add_songs_to_playlist failed: {exc}")
            return False

    def update_playlist(
        self,
        playlist_id: str,
        name: str | None = None,
        comment: str | None = None,
        public: bool | None = None,
    ) -> bool:
        """Update a playlist's metadata on the server."""
        try:
            params: dict = {"playlistId": playlist_id}
            if name    is not None: params["name"]    = name
            if comment is not None: params["comment"] = comment
            if public  is not None: params["public"]  = "true" if public else "false"
            self._http.get("updatePlaylist.view", params)
            logger.info(f"update_playlist({playlist_id!r}): {params}")
            return True
        except Exception as exc:
            logger.warning(f"update_playlist failed: {exc}")
            return False

    def get_lyrics_by_id(self, song_id: str) -> dict | None:
        """Return structured lyrics from getLyricsBySongId (OpenSubsonic extension).

        Returns the first structuredLyrics entry, or None if unavailable.
        Synced entries include 'synced': True and 'line': [{'start': ms, 'value': str}].
        """
        try:
            data = self._http.get("getLyricsBySongId.view", {"id": song_id})
            items = data.get("lyricsList", {}).get("structuredLyrics", [])
            if items:
                # Prefer synced over unsynced
                synced = [i for i in items if i.get("synced")]
                return (synced or items)[0]
        except Exception as exc:
            logger.debug(f"getLyricsBySongId({song_id}) unavailable: {exc}")
        return None

    def get_lyrics(self, artist: str, title: str) -> str:
        """Return plain-text lyrics string, or empty string on failure."""
        try:
            data = self._http.get("getLyrics.view", {"artist": artist, "title": title})
            return data.get("lyrics", {}).get("value", "") or ""
        except Exception as exc:
            logger.warning(f"get_lyrics({title!r}) failed: {exc}")
        return ""

    def ping(self) -> bool:
        """Return True if the server is reachable and credentials are valid."""
        try:
            self._http.get("ping.view")
            return True
        except Exception:
            return False
