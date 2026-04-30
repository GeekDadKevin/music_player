"""Playlist page — single-pane track viewer.

Navigation between playlists is handled by the sidebar, not this page.
This page shows the tracks for whatever playlist is currently selected,
plus an Import button and a Sync button for imported playlists.
"""

import os

from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot, QThread, QTimer
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QScrollArea, QTextEdit,
    QVBoxLayout, QWidget,
)

from src.music_player.logging import get_logger
from src.music_player.repository.playlist_db import (
    load_all as db_load_all,
    save_playlist as db_save,
    update_track as db_update_track,
)
from src.music_player.ui.components.track_table import TrackTable
from src.music_player.ui.glyphs import ADD, MDL2_FAMILY_CSS, MDL2_FONT, PLAY, SEARCH, SHUFFLE, SYNC
from src.music_player.ui.workers.playlist_import import PlaylistImportWorker
from src.music_player.ui.workers.playlists import LoadPlaylistTracksWorker

logger = get_logger(__name__)


class PlaylistPage(QWidget):
    """Single-pane playlist viewer.

    Call show_server_playlist() or show_imported_playlist() from the sidebar
    signal handler.  playlist_imported is emitted after a successful import
    so the sidebar can add the new playlist.
    """

    playlist_imported  = pyqtSignal(str)                 # name of the newly imported playlist
    playlist_renamed   = pyqtSignal(str, str, str, str)  # old_name, new_name, source, pl_id
    playlist_deleted   = pyqtSignal(str, str)            # name, source
    playlist_created   = pyqtSignal(str, str)            # name, pl_id
    playlist_activated = pyqtSignal(str)                 # name — for sidebar highlight

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._playlists: dict[str, dict] = {}
        self._server_playlists: dict[str, str] = {}   # name → server id
        self._current_name   = ""
        self._current_source = ""   # "server" or "import"
        self._current_pl_id  = ""
        self._current_meta: dict = {}   # full server playlist dict (comment, public, coverArt…)
        self._local_meta: dict[str, dict] = {}  # name → {description} for imported playlists
        self._active_workers: list = []
        self._build_ui()
        self._load_db_playlists()

    # ── public API (called from sidebar / app.py) ─────────────────────

    def show_server_playlist(self, pl_id: str, name: str) -> None:
        from src.music_player.ui.last_playlist import set_last
        set_last(name, pl_id)
        self._server_playlists[name] = pl_id
        self._current_name   = name
        self._current_source = "server"
        self._current_pl_id  = pl_id
        self._heading.setText(name)
        self._description.setText("")
        self._sync_btn.setVisible(False)
        self._edit_btn.setVisible(True)
        self._play_actions.setVisible(True)
        self._art.clear()
        self._art.setStyleSheet("border-radius:8px; background:#2a2a2e;")
        self.playlist_activated.emit(name)
        if name in self._playlists:
            pl_data = self._playlists[name]
            self._current_meta = pl_data.get("meta", {})
            self._description.setText(self._current_meta.get("comment", ""))
            self._load_cover_art(self._current_meta, pl_data.get("matched", []))
            self._show_cached(name)
        else:
            self._load_server_tracks(name, pl_id)

    def show_imported_playlist(self, name: str) -> None:
        self._current_name   = name
        self._current_source = "import"
        self._current_pl_id  = ""
        self._heading.setText(name)
        self._description.setText(self._local_meta.get(name, {}).get("description", ""))
        self._sync_btn.setVisible(True)
        self._edit_btn.setVisible(True)
        self._play_actions.setVisible(True)
        self.playlist_activated.emit(name)
        self._art.clear()
        self._art.setStyleSheet("border-radius:8px; background:#2a2a2e;")
        # Show cached cover if previously uploaded
        import src.music_player.image_store as image_store
        cover = image_store.get(self._cover_key())
        if cover:
            self._set_art(cover)
        self._show_cached(name)

    def get_imported_names(self) -> list[str]:
        """Return names of all locally imported playlists (for the sidebar)."""
        return [n for n, d in self._playlists.items() if d.get("source") == "import"]

    # ── build UI ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.setStyleSheet("background:#111114;")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header: large art + name/description ──────────────────────
        header = QHBoxLayout()
        header.setContentsMargins(16, 16, 16, 6)
        header.setSpacing(16)

        # Left column: art + play buttons stacked beneath it
        left_col = QVBoxLayout()
        left_col.setSpacing(8)
        left_col.setContentsMargins(0, 0, 0, 0)

        self._art = QLabel()
        self._art.setFixedSize(140, 140)
        self._art.setStyleSheet("border-radius:8px; background:#2a2a2e;")
        self._art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_col.addWidget(self._art)

        # Play / Shuffle / Add-to-queue — hidden until a playlist is opened
        self._play_actions = QWidget()
        self._play_actions.setStyleSheet("background:transparent;")
        self._play_actions.setVisible(False)
        pa = QHBoxLayout(self._play_actions)
        pa.setContentsMargins(0, 0, 0, 0)
        pa.setSpacing(6)

        _outline = (
            "QPushButton{background:transparent;color:#aaa;font-size:11px;"
            f"font-family:{MDL2_FAMILY_CSS};border:1px solid #444;"
            "border-radius:14px;padding:4px 12px;}"
            "QPushButton:hover{background:#2a2a2e;color:#fff;border-color:#666;}"
        )
        _primary = (
            "QPushButton{background:#2dd4bf;color:#000;font-size:11px;font-weight:700;"
            f"font-family:{MDL2_FAMILY_CSS};border:none;border-radius:14px;padding:4px 14px;}}"
            "QPushButton:hover{background:#38ebd5;}"
        )

        _pa_play    = QPushButton(f"{PLAY}  Play")
        _pa_shuffle = QPushButton(f"{SHUFFLE}  Shuffle")
        _pa_append  = QPushButton(f"{ADD}  Add to queue")
        for btn in (_pa_play, _pa_shuffle, _pa_append):
            btn.setFont(QFont(MDL2_FONT, 10))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _pa_play.setStyleSheet(_primary)
        _pa_shuffle.setStyleSheet(_outline)
        _pa_append.setStyleSheet(_outline)
        _pa_play.clicked.connect(lambda: self._on_play_action("play"))
        _pa_shuffle.clicked.connect(lambda: self._on_play_action("shuffle"))
        _pa_append.clicked.connect(lambda: self._on_play_action("append"))
        pa.addWidget(_pa_play)
        pa.addWidget(_pa_shuffle)
        pa.addWidget(_pa_append)
        pa.addStretch()

        left_col.addWidget(self._play_actions)
        left_col.addStretch()
        header.addLayout(left_col)

        meta_col = QVBoxLayout()
        meta_col.setSpacing(6)
        meta_col.setContentsMargins(0, 4, 0, 4)

        self._heading = QLabel("Playlists")
        self._heading.setStyleSheet(
            "color:#fff; font-size:22px; font-weight:700; background:transparent;"
        )
        self._heading.setWordWrap(True)

        self._description = QLabel("")
        self._description.setStyleSheet("color:#888; font-size:13px; background:transparent;")
        self._description.setWordWrap(True)

        meta_col.addStretch()
        meta_col.addWidget(self._heading)
        meta_col.addWidget(self._description)
        meta_col.addStretch()
        header.addLayout(meta_col, stretch=1)

        root.addLayout(header)

        # ── Action buttons (right-aligned, below header) ───────────────
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(16, 0, 16, 8)
        btn_row.setSpacing(8)
        btn_row.addStretch()

        self._edit_btn = QPushButton("Edit")
        self._edit_btn.setVisible(False)
        self._edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._edit_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#aaa;font-size:12px;"
            "border:1px solid #444;border-radius:6px;padding:5px 12px;}"
            "QPushButton:hover{background:#2a2a2e;color:#fff;}"
        )
        self._edit_btn.clicked.connect(self._on_edit)
        btn_row.addWidget(self._edit_btn)

        self._sync_btn = QPushButton(f"{SYNC}  Sync to Server")
        self._sync_btn.setVisible(False)
        self._sync_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sync_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:#2dd4bf;font-size:12px;"
            f"font-family:{MDL2_FAMILY_CSS};border:1px solid #2dd4bf;"
            "border-radius:6px;padding:5px 12px;}"
            "QPushButton:hover{background:#2dd4bf;color:#000;}"
            "QPushButton:disabled{color:#444;border-color:#333;}"
        )
        self._sync_btn.clicked.connect(self._on_sync)
        btn_row.addWidget(self._sync_btn)

        create_btn = QPushButton("+ New Playlist")
        create_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        create_btn.setStyleSheet(
            "QPushButton{background:#2dd4bf;color:#000;font-size:12px;font-weight:700;"
            "border:none;border-radius:6px;padding:6px 14px;}"
            "QPushButton:hover{background:#38ebd5;}"
        )
        create_btn.clicked.connect(self._on_create)
        btn_row.addWidget(create_btn)

        import_btn = QPushButton("+ Import M3U / JSPF")
        import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#2dd4bf;font-size:12px;font-weight:700;"
            "border:1px solid #2dd4bf;border-radius:6px;padding:6px 14px;}"
            "QPushButton:hover{background:#2dd4bf;color:#000;}"
        )
        import_btn.clicked.connect(self._on_import)
        btn_row.addWidget(import_btn)

        root.addLayout(btn_row)

        self._status = QLabel("")
        self._status.setStyleSheet(
            "color:#888; font-size:12px; margin:0 16px 4px 16px; background:transparent;"
        )
        root.addWidget(self._status)

        self._track_table = TrackTable()
        self._track_table.search_requested.connect(self._on_search_requested)
        root.addWidget(self._track_table, stretch=1)

    # ── data loading ──────────────────────────────────────────────────

    def _load_db_playlists(self) -> None:
        for pl in db_load_all():
            self._playlists[pl["name"]] = {
                "matched": pl["matched"],
                "raw":     pl["raw"],
                "source":  "import",
            }
            if pl.get("description"):
                self._local_meta[pl["name"]] = {"description": pl["description"]}

    def _load_server_tracks(self, name: str, playlist_id: str) -> None:
        self._status.setText(f"Loading {name}…")
        w = LoadPlaylistTracksWorker(playlist_id, parent=self)
        w.tracks_loaded.connect(
            lambda tracks, info, n=name: self._on_server_tracks(tracks, n, info)
        )
        w.error.connect(lambda e: self._status.setText(f"Error: {e}"))
        self._active_workers.append(w)
        w.start()

    def _on_server_tracks(self, tracks: list, name: str, meta: dict) -> None:
        self._status.setText("")
        self._playlists[name] = {"matched": tracks, "raw": tracks, "source": "server", "meta": meta}
        if self._current_name == name:
            self._current_meta = meta
            self._description.setText(meta.get("comment", ""))
            self._load_cover_art(meta, tracks)
            self._show_cached(name)

    def _cover_key(self) -> str:
        """Stable image_store key for this playlist's custom/composite cover."""
        if self._current_pl_id:
            return f"playlist:{self._current_pl_id}"
        return f"playlist_import:{self._current_name}"

    def _load_cover_art(self, meta: dict, tracks: list | None = None) -> None:
        import src.music_player.image_store as image_store
        pl_id = meta.get("id", self._current_pl_id)

        key = self._cover_key()

        # 1. User-uploaded or cached composite takes priority
        uploaded = image_store.get(key)
        if uploaded:
            self._set_art(uploaded)
            return

        # 2. Server-provided coverArt
        cover_id = meta.get("coverArt", "")
        if cover_id:
            data = image_store.get(f"album:{cover_id}")
            if data:
                self._set_art(data)
            else:
                from src.music_player.ui.workers.image_loader import AlbumCoverLoader, _launch
                loader = AlbumCoverLoader(cover_id)
                loader.loaded.connect(self._set_art)
                _launch(loader)
            return

        # 3. Build a 2×2 composite from tracks in the playlist
        if tracks:
            composite = _make_playlist_composite(tracks, 64)
            if composite:
                image_store.put(key, composite, source="composite")
                self._set_art(composite)

    @pyqtSlot(bytes)
    def _set_art(self, data: bytes) -> None:
        if not data:
            return
        px = QPixmap()
        if px.loadFromData(data):
            self._art.setPixmap(
                px.scaled(140, 140, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                          Qt.TransformationMode.SmoothTransformation).copy(0, 0, 140, 140)
            )
            self._art.setStyleSheet("border-radius:8px;")

    def _show_cached(self, name: str) -> None:
        data = self._playlists.get(name)
        if not data:
            return
        matched = data["matched"]
        raw     = data["raw"]
        n_miss  = sum(1 for m in matched if m is None)
        self._status.setText(
            f"{n_miss} track(s) not found — right-click to search" if n_miss else ""
        )
        self._track_table.set_playlist_tracks(matched, raw)

    def _on_play_action(self, mode: str) -> None:
        tracks = self._playlists.get(self._current_name, {}).get("matched", [])
        self._execute_play(tracks, mode)

    # ── play from sidebar ────────────────────────────────────────────

    def play_playlist(self, pl_id: str, name: str, mode: str) -> None:
        """Play / shuffle-play / append all matched tracks from a playlist.

        mode: "play" | "shuffle" | "append"
        Fetches tracks from the server first if they haven't been loaded yet.
        """
        data = self._playlists.get(name)
        if data is not None:
            self._execute_play(data.get("matched", []), mode)
        elif pl_id:
            w = LoadPlaylistTracksWorker(pl_id, parent=self)
            w.tracks_loaded.connect(
                lambda tracks, info, n=name, m=mode:
                    self._on_fetch_and_play(tracks, info, n, m)
            )
            self._active_workers.append(w)
            w.start()

    def _on_fetch_and_play(self, tracks: list, info: dict, name: str, mode: str) -> None:
        self._playlists[name] = {
            "matched": tracks, "raw": tracks, "source": "server", "meta": info,
        }
        self._execute_play(tracks, mode)

    def _execute_play(self, tracks: list, mode: str) -> None:
        import random
        from src.music_player.queue import get_queue
        from src.music_player.ui.components.playback_bridge import get_bridge
        valid = [t for t in tracks if t and t.get("id")]
        if not valid:
            return
        q = get_queue()
        bridge = get_bridge()
        if mode == "append":
            q.add_tracks(valid)
            bridge.queue_changed.emit()
        else:
            if mode == "shuffle":
                valid = random.sample(valid, len(valid))
            q.set_queue(valid, 0)
            bridge.play_track(valid[0])
            bridge.queue_changed.emit()

    # ── import ────────────────────────────────────────────────────────

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Playlist",
            os.path.expanduser("~"),
            "Playlist files (*.m3u *.m3u8 *.jspf);;All files (*)",
        )
        if not path:
            return

        name = os.path.splitext(os.path.basename(path))[0]
        self._playlists[name] = {"matched": [], "raw": [], "source": "import"}
        self._current_name   = name
        self._current_source = "import"
        self._heading.setText(name)
        self._sync_btn.setVisible(True)
        self._status.setText(f"Importing {name}…")
        self._track_table.setRowCount(0)

        w = PlaylistImportWorker(path, parent=self)
        w.progress.connect(lambda done, total, msg: self._status.setText(msg))
        w.track_result.connect(
            lambda idx, matched, raw, n=name: self._on_track_result(n, idx, matched, raw)
        )
        w.finished.connect(lambda title, n=name: self._on_import_done(n))
        w.error.connect(lambda e: self._status.setText(f"Import error: {e}"))
        self._active_workers.append(w)
        w.start()

    def _on_track_result(self, playlist_name: str, index: int, matched, raw: dict) -> None:
        data = self._playlists.get(playlist_name)
        if data is None:
            return
        while len(data["matched"]) <= index:
            data["matched"].append(None)
            data["raw"].append({})
        data["matched"][index] = matched
        data["raw"][index]     = raw
        if self._current_name == playlist_name:
            self._show_cached(playlist_name)

    def _on_import_done(self, name: str) -> None:
        data = self._playlists.get(name, {})
        matched   = data.get("matched", [])
        raw       = data.get("raw", [])
        n_matched = sum(1 for m in matched if m is not None)
        n_total   = len(matched)
        n_miss    = n_total - n_matched
        msg = f"Import complete: {n_matched}/{n_total} tracks matched"
        if n_miss:
            msg += f" — {n_miss} not found (right-click to search)"
        self._status.setText(msg)
        db_save(name, matched, raw)
        self.playlist_imported.emit(name)

    # ── sync ──────────────────────────────────────────────────────────

    def _on_sync(self) -> None:
        if not self._current_name:
            return
        data     = self._playlists.get(self._current_name, {})
        song_ids = [m["id"] for m in data.get("matched", []) if m and m.get("id")]
        if not song_ids:
            self._status.setText("No matched tracks to sync.")
            return
        self._sync_btn.setEnabled(False)
        self._status.setText(f"Syncing '{self._current_name}' ({len(song_ids)} tracks)…")
        w = _SyncWorker(self._current_name, song_ids, parent=self)
        w.done.connect(self._on_sync_done)
        w.failed.connect(
            lambda msg: (self._status.setText(f"Sync failed: {msg}"),
                         self._sync_btn.setEnabled(True))
        )
        self._active_workers.append(w)
        w.start()

    def _on_sync_done(self, playlist_name: str, server_id: str) -> None:
        self._sync_btn.setEnabled(True)
        self._status.setText(f"'{playlist_name}' synced to server.")
        self._server_playlists[playlist_name] = server_id

    # ── unmatched search ──────────────────────────────────────────────

    @pyqtSlot(int, dict)
    def _on_search_requested(self, row: int, raw: dict) -> None:
        if not self._current_name:
            return
        dlg = TrackSearchDialog(
            prefill_title=raw.get("title", ""),
            prefill_artist=raw.get("artist", ""),
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_track:
            track = dlg.selected_track
            data  = self._playlists.get(self._current_name, {})
            if data and row < len(data["matched"]):
                data["matched"][row] = track
                data["raw"][row].update(track)
            self._track_table.resolve_unmatched(row, track)
            db_update_track(self._current_name, row, track)
            from src.music_player.repository.subsonic_client import SubsonicClient
            _TriggerWorker(SubsonicClient(), track["id"], parent=self).start()
            matched = data.get("matched", [])
            n_miss  = sum(1 for m in matched if m is None)
            self._status.setText(
                f"{n_miss} track(s) still unmatched" if n_miss else "All tracks matched"
            )


    # ── create playlist ───────────────────────────────────────────────

    def _on_create(self) -> None:
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "New Playlist", "Playlist name:", text=""
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        self._status.setText(f"Creating '{name}'…")
        w = _CreatePlaylistWorker(name, parent=self)
        w.done.connect(lambda pl: self._on_created(name, pl))
        w.failed.connect(lambda msg: self._status.setText(f"Error: {msg}"))
        self._active_workers.append(w)
        w.start()

    def _on_created(self, name: str, pl: dict) -> None:
        pl_id = str(pl.get("id", ""))
        self._status.setText("")
        self.playlist_created.emit(name, pl_id)
        self.show_server_playlist(pl_id, name)

    # ── delete playlist ───────────────────────────────────────────────

    def _delete_current_playlist(self) -> None:
        if self._current_source == "server":
            w = _DeletePlaylistWorker(self._current_pl_id, parent=self)
            w.done.connect(self._on_server_deleted)
            w.failed.connect(lambda msg: self._status.setText(f"Delete failed: {msg}"))
            self._active_workers.append(w)
            w.start()
        else:
            from src.music_player.repository.playlist_db import delete_playlist as db_del
            db_del(self._current_name)
            self._playlists.pop(self._current_name, None)
            name = self._current_name
            self._current_name = ""
            self._heading.setText("Playlists")
            self._description.setText("")
            self._track_table.set_tracks([])
            self.playlist_deleted.emit(name, "import")

    def _on_server_deleted(self) -> None:
        name = self._current_name
        self._playlists.pop(name, None)
        self._current_name = ""
        self._heading.setText("Playlists")
        self._description.setText("")
        self._track_table.set_tracks([])
        self.playlist_deleted.emit(name, "server")

    # ── upload custom cover ───────────────────────────────────────────

    def _on_upload_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose Playlist Image",
            os.path.expanduser("~"),
            "Images (*.png *.jpg *.jpeg *.webp);;All files (*)",
        )
        if not path:
            return
        try:
            import src.music_player.image_store as image_store
            with open(path, "rb") as fh:
                raw = fh.read()
            image_store.put(self._cover_key(), raw, source="upload")
            self._set_art(raw)
        except Exception as exc:
            logger.warning(f"Playlist image upload failed: {exc}")

    # ── edit playlist ─────────────────────────────────────────────────

    def _on_edit(self) -> None:
        is_server = self._current_source == "server"
        if is_server:
            name    = self._current_meta.get("name", self._current_name)
            comment = self._current_meta.get("comment", "")
            public  = self._current_meta.get("public", False)
        else:
            name    = self._current_name
            comment = self._local_meta.get(self._current_name, {}).get("description", "")
            public  = False

        dlg = _EditPlaylistDialog(
            pl_id            = self._current_pl_id,
            name             = name,
            comment          = comment,
            public           = public,
            is_server        = is_server,
            upload_image_cb  = self._on_upload_image,
            parent           = self,
        )
        code = dlg.exec()
        if dlg.delete_confirmed:
            self._delete_current_playlist()
            return
        if code == QDialog.DialogCode.Accepted:
            result   = dlg.result_data
            old_name = self._current_name
            new_name = result["name"]
            comment  = result["comment"]

            self._heading.setText(new_name)
            self._description.setText(comment)

            if is_server:
                self._current_meta.update(result)
                self._server_playlists[new_name] = self._server_playlists.pop(old_name, self._current_pl_id)
            else:
                # Persist to local DB
                from src.music_player.repository.playlist_db import rename_playlist as db_rename
                db_rename(old_name, new_name, comment)
                self._local_meta.setdefault(new_name, {})["description"] = comment
                if old_name in self._playlists:
                    self._playlists[new_name] = self._playlists.pop(old_name)
                if old_name in self._local_meta and old_name != new_name:
                    self._local_meta.pop(old_name, None)

            self._current_name = new_name
            self.playlist_renamed.emit(old_name, new_name, self._current_source, self._current_pl_id)


# ── composite cover builder ────────────────────────────────────────────

def _make_playlist_composite(tracks: list, size: int = 64) -> bytes:
    """Build a 2×2 grid image from up to 4 distinct album covers in the playlist.

    Runs on the main thread (uses QPixmap).  Returns PNG bytes, or b'' if no
    cached album art is available.
    """
    import random
    import src.music_player.image_store as image_store
    from PyQt6.QtCore import QBuffer, QIODevice, Qt
    from PyQt6.QtGui import QPainter, QPixmap

    # Collect distinct cached album-art blobs (deduplicated by coverArt ID)
    seen: set[str] = set()
    pool: list[bytes] = []
    candidates = list(tracks)
    random.shuffle(candidates)
    for t in candidates:
        cid = t.get("coverArt", "")
        if cid and cid not in seen:
            data = image_store.get(f"album:{cid}")
            if data:
                seen.add(cid)
                pool.append(data)
        if len(pool) == 4:
            break

    if not pool:
        return b""

    # Decode into QPixmaps
    pxs: list[QPixmap] = []
    for blob in pool:
        px = QPixmap()
        if px.loadFromData(blob) and not px.isNull():
            pxs.append(px)

    if not pxs:
        return b""

    half = size // 2
    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.black)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    positions = [(0, 0), (half, 0), (0, half), (half, half)]
    for i, (x, y) in enumerate(positions):
        src = pxs[i % len(pxs)]   # wrap if fewer than 4 distinct images
        scaled = src.scaled(half, half,
                            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation)
        ox = (scaled.width()  - half) // 2
        oy = (scaled.height() - half) // 2
        painter.drawPixmap(x, y, scaled, ox, oy, half, half)

    painter.end()

    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    result.save(buf, "PNG")
    return bytes(buf.data())


# ── workers ───────────────────────────────────────────────────────────

class _CreatePlaylistWorker(QThread):
    done   = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, name: str, parent=None) -> None:
        super().__init__(parent)
        self._name = name

    def run(self) -> None:
        from src.music_player.repository.subsonic_client import SubsonicClient
        pl = SubsonicClient().create_playlist(self._name, [])
        if pl:
            self.done.emit(pl)
        else:
            self.failed.emit("Server returned no playlist.")


class _DeletePlaylistWorker(QThread):
    done   = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, pl_id: str, parent=None) -> None:
        super().__init__(parent)
        self._pl_id = pl_id

    def run(self) -> None:
        from src.music_player.repository.subsonic_client import SubsonicClient
        ok = SubsonicClient().delete_playlist(self._pl_id)
        if ok:
            self.done.emit()
        else:
            self.failed.emit("Server returned an error.")


class _SyncWorker(QThread):
    done   = pyqtSignal(str, str)
    failed = pyqtSignal(str)

    def __init__(self, name: str, song_ids: list, parent=None) -> None:
        super().__init__(parent)
        self._name     = name
        self._song_ids = song_ids

    def run(self) -> None:
        from src.music_player.repository.subsonic_client import SubsonicClient
        pl = SubsonicClient().create_playlist(self._name, self._song_ids)
        if pl:
            self.done.emit(self._name, str(pl.get("id", "")))
        else:
            self.failed.emit("Server returned no playlist.")


class _TriggerWorker(QThread):
    def __init__(self, client, song_id: str, parent=None) -> None:
        super().__init__(parent)
        self._client  = client
        self._song_id = song_id

    def run(self) -> None:
        from src.music_player.ui.workers.playlist_import import _trigger_download
        _trigger_download(self._client, self._song_id)


# ── edit playlist dialog ───────────────────────────────────────────────

class _EditPlaylistDialog(QDialog):
    def __init__(self, pl_id: str, name: str, comment: str, public: bool,
                 is_server: bool = True, upload_image_cb=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Playlist")
        self.setMinimumWidth(420)
        self.setStyleSheet("background:#111114; color:#ddd;")
        self.result_data:    dict = {}
        self.delete_confirmed: bool = False
        self._pl_id    = pl_id
        self._is_server = is_server
        self._upload_image_cb = upload_image_cb
        self._worker   = None

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(20, 20, 20, 16)

        def _field(label: str, widget) -> None:
            lbl = QLabel(label)
            lbl.setStyleSheet("color:#aaa; font-size:12px; background:transparent;")
            root.addWidget(lbl)
            root.addWidget(widget)

        self._name = QLineEdit(name)
        self._name.setStyleSheet(
            "QLineEdit{background:#1e1e22;color:#fff;border:1px solid #333;"
            "border-radius:4px;padding:6px 10px;font-size:13px;}"
            "QLineEdit:focus{border-color:#2dd4bf;}"
        )
        _field("Name", self._name)

        self._comment = QTextEdit()
        self._comment.setPlainText(comment)
        self._comment.setFixedHeight(80)
        self._comment.setStyleSheet(
            "QTextEdit{background:#1e1e22;color:#fff;border:1px solid #333;"
            "border-radius:4px;padding:6px 10px;font-size:13px;}"
            "QTextEdit:focus{border-color:#2dd4bf;}"
        )
        _field("Description", self._comment)

        self._public = QCheckBox("Public (visible to other users on the server)")
        self._public.setChecked(bool(public))
        self._public.setStyleSheet(
            "QCheckBox{color:#ccc; background:transparent;}"
            "QCheckBox::indicator{width:16px;height:16px;border-radius:3px;"
            "border:1px solid #444;background:#1e1e22;}"
            "QCheckBox::indicator:checked{background:#2dd4bf;border-color:#2dd4bf;}"
        )
        self._public.setVisible(is_server)   # only relevant for server playlists
        root.addWidget(self._public)

        if upload_image_cb is not None:
            upload_btn = QPushButton("Upload Cover Image…")
            upload_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            upload_btn.setStyleSheet(
                "QPushButton{background:#1e1e22;color:#aaa;border:1px solid #444;"
                "border-radius:4px;padding:5px 14px;font-size:12px;}"
                "QPushButton:hover{background:#2a2a2e;color:#fff;}"
            )
            upload_btn.clicked.connect(upload_image_cb)
            root.addWidget(upload_btn)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#888; font-size:11px; background:transparent;")
        root.addWidget(self._status)

        btn_row = QHBoxLayout()

        delete_btn = QPushButton("Delete Playlist")
        delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#e55;border:1px solid #833;"
            "border-radius:4px;padding:5px 14px;font-size:12px;}"
            "QPushButton:hover{background:#e55;color:#fff;}"
        )
        delete_btn.clicked.connect(self._confirm_delete)
        btn_row.addWidget(delete_btn)
        btn_row.addStretch()

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.setStyleSheet(
            "QDialogButtonBox QPushButton{background:#1e1e22;color:#ddd;"
            "border:1px solid #333;border-radius:4px;padding:5px 16px;min-width:60px;}"
            "QDialogButtonBox QPushButton:hover{background:#2a2a2e;}"
        )
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        btn_row.addWidget(btns)
        root.addLayout(btn_row)

    def _confirm_delete(self) -> None:
        from PyQt6.QtWidgets import QMessageBox
        ans = QMessageBox.question(
            self,
            "Delete Playlist",
            f"Permanently delete this playlist?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if ans == QMessageBox.StandardButton.Yes:
            self.delete_confirmed = True
            self.reject()   # close dialog without Save

    def _save(self) -> None:
        new_name    = self._name.text().strip()
        new_comment = self._comment.toPlainText().strip()
        new_public  = self._public.isChecked()
        if not new_name:
            self._status.setText("Name cannot be empty.")
            return
        if not self._is_server:
            # Imported playlist — save locally, no server call needed
            self.result_data = {"name": new_name, "comment": new_comment, "public": False}
            self.accept()
            return
        self._status.setText("Saving…")
        self._worker = _UpdatePlaylistWorker(
            self._pl_id, new_name, new_comment, new_public, parent=self
        )
        self._worker.done.connect(lambda ok: self._on_saved(ok, new_name, new_comment, new_public))
        self._worker.start()

    def _on_saved(self, ok: bool, name: str, comment: str, public: bool) -> None:
        if ok:
            self.result_data = {"name": name, "comment": comment, "public": public}
            self.accept()
        else:
            self._status.setText("Failed to save — check server connection.")


class _UpdatePlaylistWorker(QThread):
    done = pyqtSignal(bool)

    def __init__(self, pl_id: str, name: str, comment: str, public: bool,
                 parent=None) -> None:
        super().__init__(parent)
        self._pl_id   = pl_id
        self._name    = name
        self._comment = comment
        self._public  = public

    def run(self) -> None:
        from src.music_player.repository.subsonic_client import SubsonicClient
        ok = SubsonicClient().update_playlist(
            self._pl_id, name=self._name,
            comment=self._comment, public=self._public,
        )
        self.done.emit(ok)


# ── search dialog ─────────────────────────────────────────────────────

class TrackSearchDialog(QDialog):
    def __init__(self, prefill_title: str = "", prefill_artist: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Search for track")
        self.setMinimumSize(600, 400)
        self.setStyleSheet("background:#111114; color:#ddd;")
        self.selected_track: dict | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        search_row = QHBoxLayout()
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Title  artist…")
        self._search_box.setText(f"{prefill_title} {prefill_artist}".strip())
        self._search_box.setStyleSheet(
            "background:#1e1e22; color:#fff; border:1px solid #333; "
            "border-radius:6px; padding:6px 10px; font-size:13px;"
        )
        search_row.addWidget(self._search_box, stretch=1)

        search_btn = QPushButton(f"{SEARCH}  Search")
        search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        search_btn.setStyleSheet(
            "QPushButton{background:#2dd4bf;color:#000;border:none;"
            "border-radius:6px;padding:6px 14px;font-weight:700;}"
            "QPushButton:hover{background:#38ebd5;}"
        )
        search_btn.clicked.connect(self._do_search)
        self._search_box.returnPressed.connect(self._do_search)
        search_row.addWidget(search_btn)
        layout.addLayout(search_row)

        self._status = QLabel("Enter a search query and press Search.")
        self._status.setStyleSheet("color:#666; font-size:12px; background:transparent;")
        layout.addWidget(self._status)

        self._result_table = TrackTable()
        self._result_table.track_activated.connect(self._on_track_activated)
        layout.addWidget(self._result_table, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.setStyleSheet("color:#ddd;")
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._worker = None
        QTimer.singleShot(0, self._do_search)

    def _do_search(self) -> None:
        query = self._search_box.text().strip()
        if not query:
            return
        self._status.setText("Searching…")
        self._result_table.set_tracks([])
        from src.music_player.ui.workers.search import SearchWorker
        if self._worker and hasattr(self._worker, "isRunning") and self._worker.isRunning():
            self._worker.quit()
        self._worker = SearchWorker(query, parent=self)
        self._worker.results_ready.connect(self._on_results)
        self._worker.error.connect(lambda e: self._status.setText(f"Error: {e}"))
        self._worker.start()

    @pyqtSlot(list)
    def _on_results(self, tracks: list) -> None:
        self._status.setText(f"{len(tracks)} result(s)" if tracks else "No results.")
        self._result_table.set_tracks(tracks)

    def _on_track_activated(self, track: dict) -> None:
        self.selected_track = track
        self.accept()

    def _on_ok(self) -> None:
        rows = self._result_table.selectedItems()
        if rows:
            row    = self._result_table.row(rows[0])
            tracks = self._result_table._tracks
            if 0 <= row < len(tracks):
                self.selected_track = tracks[row]
        self.accept()
