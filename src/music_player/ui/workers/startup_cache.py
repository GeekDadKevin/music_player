"""Startup cache worker — fast initialisation only.

Does NOT download images; those are fetched on demand when views are opened.

Flow
----
1. Preload all SQLite images into RAM  (fast, local)
2. Fetch artist list + album list from Subsonic in parallel
3. Store artist list for instant tab render
4. Emit finished()
"""

import concurrent.futures

from PyQt6.QtCore import QThread, pyqtSignal

import src.music_player.image_store as image_store
from src.music_player.logging import get_logger
from src.music_player.repository.subsonic_client import SubsonicClient

logger = get_logger(__name__)


class StartupCacheWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal()

    def run(self) -> None:
        try:
            # 1. Preload SQLite cache into RAM
            count = image_store.preload()
            self.progress.emit(0, 0, f"Loaded {count} cached images")

            # 2. Fetch artist, album, and playlist lists in parallel
            self.progress.emit(0, 0, "Connecting to library…")
            client = SubsonicClient()
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                af = pool.submit(client.get_artists)
                lf = pool.submit(client.get_all_albums)
                pf = pool.submit(client.get_playlists)
                gf = pool.submit(client.get_genres)
                try:
                    artists = af.result(timeout=30)
                except Exception as exc:
                    logger.error(f"get_artists failed: {exc}")
                    artists = []
                try:
                    albums = lf.result(timeout=60)
                except Exception as exc:
                    logger.error(f"get_all_albums failed: {exc}")
                    albums = []
                try:
                    playlists = pf.result(timeout=30)
                except Exception as exc:
                    logger.error(f"get_playlists failed: {exc}")
                    playlists = []
                try:
                    genres = gf.result(timeout=30)
                except Exception as exc:
                    logger.error(f"get_genres failed: {exc}")
                    genres = []

            # 3. Store lists so Browse tabs render instantly
            image_store.set_artists(artists)
            image_store.set_albums(albums)
            image_store.set_playlists(playlists)
            image_store.set_genres(genres)
            self.progress.emit(0, 0, f"Ready — {len(artists)} artists, {len(albums)} albums")

        except Exception as exc:
            logger.error(f"StartupCacheWorker error: {exc}")
        finally:
            self.finished.emit()
