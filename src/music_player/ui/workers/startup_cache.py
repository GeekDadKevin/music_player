"""Startup cache worker — fast initialisation only.

Flow
----
1. Preload all SQLite images into RAM  (fast, local)
2. Trigger Navidrome library scan (picks up files downloaded while app was closed)
3. Fetch artist / album / playlist / genre lists from Subsonic in parallel
4. Store lists so Browse tabs render instantly
5. Emit finished()
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
            logger.info("startup: preloading image cache")
            count = image_store.preload()
            self.progress.emit(0, 0, f"Loaded {count} cached images")
            logger.info(f"startup: image cache ready ({count} images)")

            # 2. Trigger a library scan so files downloaded while the app was
            #    closed get indexed before we fetch the library lists.
            self.progress.emit(0, 0, "Scanning library for new files…")
            logger.info("startup: triggering library scan")
            client = SubsonicClient()
            try:
                client.start_scan()
                logger.info("startup: library scan triggered ok")
            except Exception as exc:
                logger.warning(f"startup: library scan failed (non-fatal): {exc}")

            # 3. Fetch library lists in parallel.
            #
            #    Each task creates its own SubsonicClient (and therefore its own
            #    httpx.Client + ssl context).  Sharing one client across threads
            #    causes concurrent SSL connection-pool operations that corrupt
            #    OpenSSL state and crash with code 0xe24c4a02.
            #
            #    IMPORTANT: use explicit shutdown(cancel_futures=True) rather than
            #    the `with` block.  If a future hangs past the result() timeout,
            #    `with ThreadPoolExecutor` calls shutdown(wait=True) which blocks
            #    forever because the timed-out future is still running internally.
            self.progress.emit(0, 0, "Connecting to library…")
            logger.info("startup: submitting parallel library fetches")
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)
            try:
                af = pool.submit(lambda: SubsonicClient().get_artists())
                lf = pool.submit(lambda: SubsonicClient().get_all_albums())
                pf = pool.submit(lambda: SubsonicClient().get_playlists())
                gf = pool.submit(lambda: SubsonicClient().get_genres())

                logger.info("startup: waiting for artists…")
                try:
                    artists = af.result(timeout=30)
                    logger.info(f"startup: artists ok ({len(artists)})")
                except Exception as exc:
                    logger.error(f"startup: get_artists failed: {exc}")
                    artists = []

                logger.info("startup: waiting for albums…")
                try:
                    albums = lf.result(timeout=60)
                    logger.info(f"startup: albums ok ({len(albums)})")
                except Exception as exc:
                    logger.error(f"startup: get_all_albums failed: {exc}")
                    albums = []

                logger.info("startup: waiting for playlists…")
                try:
                    playlists = pf.result(timeout=30)
                    logger.info(f"startup: playlists ok ({len(playlists)})")
                except Exception as exc:
                    logger.error(f"startup: get_playlists failed: {exc}")
                    playlists = []

                logger.info("startup: waiting for genres…")
                try:
                    genres = gf.result(timeout=30)
                    logger.info(f"startup: genres ok ({len(genres)})")
                except Exception as exc:
                    logger.error(f"startup: get_genres failed: {exc}")
                    genres = []

            finally:
                # Cancel any futures that didn't complete within their timeouts
                # so the pool doesn't block shutdown indefinitely.
                pool.shutdown(wait=False, cancel_futures=True)
                logger.info("startup: pool shut down")

            # 4. Store lists so Browse tabs render instantly
            logger.info("startup: storing lists in image_store")
            image_store.set_artists(artists)
            image_store.set_albums(albums)
            image_store.set_playlists(playlists)
            image_store.set_genres(genres)
            self.progress.emit(0, 0, f"Ready — {len(artists)} artists, {len(albums)} albums")
            logger.info("startup: all lists stored, emitting finished")

        except Exception as exc:
            logger.error(f"StartupCacheWorker unhandled error: {exc}", exc_info=True)
        finally:
            self.finished.emit()
