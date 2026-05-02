from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView, QHeaderView, QMenu, QSizePolicy, QTableWidget, QTableWidgetItem,
)

from src.music_player.logging import get_logger
from src.music_player.queue import get_queue
from src.music_player.ui.components.playback_bridge import get_bridge
from src.music_player.ui.glyphs import ADD, MDL2_FAMILY_CSS, NEXT, PLAY, SEARCH
from src.music_player.ui.navigation import nav_bus

_LINK_COLOR = "#5eead4"   # lighter teal — marks clickable artist/album cells
_COL_ARTIST = 2
_COL_ALBUM  = 3

logger = get_logger(__name__)

_COL_PROPORTIONS = {
    0: 0.04,   # #
    1: 0.38,   # Title
    2: 0.25,   # Artist
    3: 0.25,   # Album
    4: 0.08,   # Duration
}
_HEADERS = ["#", "Title", "Artist", "Album", "Duration"]


def _fmt_duration(seconds: int) -> str:
    m, s = divmod(int(seconds or 0), 60)
    return f"{m}:{s:02d}"


class TrackTable(QTableWidget):
    """Shared track listing.

    Default mode: expanding / scrollable — use it directly in a layout.
    Embedded mode: call embed_in_scroll_area() when placing inside a parent
    QScrollArea so the table expands to its full row count and the outer
    area handles scrolling.

    Column resizing:
    All columns use Interactive mode so users can drag the header border just
    like Excel.  Default proportional widths are applied on the first paint
    (resizeEvent); after that columns stay at whatever the user set.

    Double-click a matched row     → replace queue, start playing.
    Right-click a matched row      → Play Now / Add to Queue / Play Next.
    Right-click an unmatched row   → Search for match (emits search_requested).
    """

    track_activated  = pyqtSignal(dict)       # matched double-click
    search_requested = pyqtSignal(int, dict)  # row, raw_info — open search dialog

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tracks:    list[dict] = []
        self._raw:       list[dict] = []
        self._unmatched: set[int]   = set()
        self._widths_set = False

        self.setColumnCount(len(_HEADERS))
        self.setHorizontalHeaderLabels(_HEADERS)

        hdr = self.horizontalHeader()
        for i in range(len(_HEADERS)):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(False)
        hdr.setMinimumSectionSize(30)

        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # Default: expanding scrollable table
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.setStyleSheet("""
            QTableWidget {
                background: #0d0d10;
                alternate-background-color: #111114;
                color: #ccc;
                border: none;
                font-size: 13px;
            }
            QTableWidget::item { padding: 0 8px; }
            QTableWidget::item:selected { background: #1db954; color: #fff; }
            QHeaderView::section {
                background: #0d0d10;
                color: #555;
                border: none;
                border-bottom: 1px solid #1e1e22;
                padding: 6px 8px;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 0.05em;
            }
            QScrollBar:vertical {
                background: #111114; width: 6px; margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #333; border-radius: 3px; min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        self.doubleClicked.connect(self._on_double_click)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.cellClicked.connect(self._on_cell_clicked)
        self.viewport().setMouseTracking(True)
        self.viewport().mouseMoveEvent = self._on_mouse_move

        from src.music_player.ui.app_settings import settings_signals
        settings_signals().changed.connect(self._on_settings_changed)

    # ── sizing modes ──────────────────────────────────────────────────

    def embed_in_scroll_area(self) -> None:
        """Switch to fixed-height mode for embedding inside a parent QScrollArea."""
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _fit_to_content(self) -> None:
        """Resize height so every row is visible (embedded mode only)."""
        h = self.horizontalHeader().height()
        h += sum(self.rowHeight(r) for r in range(self.rowCount()))
        self.setFixedHeight(h + 2)

    # ── public API ────────────────────────────────────────────────────

    def set_tracks(self, tracks: list[dict]) -> None:
        """Populate with fully-matched tracks."""
        self._tracks    = list(tracks)
        self._raw       = list(tracks)
        self._unmatched = set()
        self._populate()

    def set_playlist_tracks(self, matched: list[dict | None], raw: list[dict]) -> None:
        """Populate from a playlist import — some entries may be None (unmatched)."""
        self._tracks    = [t if t is not None else {} for t in matched]
        self._raw       = list(raw)
        self._unmatched = {i for i, t in enumerate(matched) if t is None}
        self._populate()

    def resolve_unmatched(self, row: int, track: dict) -> None:
        """Mark a previously unmatched row as matched."""
        if row < len(self._tracks):
            self._tracks[row] = track
            self._raw[row].update(track)
            self._unmatched.discard(row)
            self._style_row(row)

    def highlight_track_id(self, track_id: str) -> None:
        for row in range(self.rowCount()):
            if row in self._unmatched:
                continue
            playing = row < len(self._tracks) and self._tracks[row].get("id") == track_id
            if playing:
                for col in range(self.columnCount()):
                    item = self.item(row, col)
                    if item:
                        f = item.font()
                        f.setBold(True)
                        item.setFont(f)
                        item.setForeground(QColor("#1db954"))
            else:
                # _style_row handles _missing (dark grey), unmatched, and normal rows
                self._style_row(row)

    # ── Qt overrides ──────────────────────────────────────────────────

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._widths_set and self.viewport().width() > 100:
            self._apply_default_widths()
            self._widths_set = True

    # ── internal ──────────────────────────────────────────────────────

    def _apply_default_widths(self) -> None:
        w = self.viewport().width()
        for col, prop in _COL_PROPORTIONS.items():
            self.setColumnWidth(col, max(30, int(w * prop)))

    def _populate(self) -> None:
        self.setRowCount(len(self._raw))
        for i, raw in enumerate(self._raw):
            if i in self._unmatched:
                t = raw
                cells = [
                    (str(i + 1),                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                    (t.get("title", "Unknown"),         Qt.AlignmentFlag.AlignLeft  | Qt.AlignmentFlag.AlignVCenter),
                    (t.get("artist", ""),               Qt.AlignmentFlag.AlignLeft  | Qt.AlignmentFlag.AlignVCenter),
                    ("",                                Qt.AlignmentFlag.AlignLeft  | Qt.AlignmentFlag.AlignVCenter),
                    (_fmt_duration(t.get("duration",0)),Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                ]
            else:
                t = self._tracks[i]
                cells = [
                    (str(t.get("track") or i + 1),     Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                    (t.get("title", ""),                Qt.AlignmentFlag.AlignLeft  | Qt.AlignmentFlag.AlignVCenter),
                    (t.get("artist", ""),               Qt.AlignmentFlag.AlignLeft  | Qt.AlignmentFlag.AlignVCenter),
                    (t.get("album", ""),                Qt.AlignmentFlag.AlignLeft  | Qt.AlignmentFlag.AlignVCenter),
                    (_fmt_duration(t.get("duration",0)),Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                ]
            for col, (text, align) in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(align)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.setItem(i, col, item)

            self._style_row(i)
            # Link-colour the artist and album cells for navigable rows
            if i not in self._unmatched and not (
                i < len(self._tracks) and self._tracks[i].get("_missing")
            ):
                for col in (_COL_ARTIST, _COL_ALBUM):
                    item = self.item(i, col)
                    if item and item.text():
                        item.setForeground(QColor(_LINK_COLOR))

        self.resizeRowsToContents()

    def _on_settings_changed(self) -> None:
        for row in range(self.rowCount()):
            self._style_row(row)

    def _style_row(self, row: int) -> None:
        from src.music_player.ui.app_settings import load_settings
        s = load_settings()
        if row in self._unmatched:
            f, colour = QFont(), QColor(s.missing_track_color)
            f.setStrikeOut(True)
        elif row < len(self._tracks) and self._tracks[row].get("_missing"):
            f, colour = QFont(), QColor(s.missing_track_color)
        elif (row < len(self._tracks) and
              self._tracks[row].get("id", "").startswith("ext-")):
            f, colour = QFont(), QColor(s.ext_track_color)
        else:
            f, colour = QFont(), QColor("#ccc")
        for col in range(self.columnCount()):
            item = self.item(row, col)
            if item:
                item.setFont(f)
                item.setForeground(colour)

    # ── slots ─────────────────────────────────────────────────────────

    def _on_double_click(self, index) -> None:
        row = index.row()
        if row in self._unmatched or row >= len(self._tracks):
            return
        t = self._tracks[row]
        if t.get("_missing") or t.get("id", "").startswith("ext-"):
            self._play_missing(t)
            return

        track = self._tracks[row]
        from src.music_player.ui.app_settings import load_settings
        action = load_settings().double_click_action

        if action == "add_to_queue":
            was_empty = get_queue().current_index < 0
            get_queue().add_track(track)
            get_bridge().queue_changed.emit()
            if was_empty:
                get_bridge().play_track(track)
            return

        if action == "play_next":
            q = get_queue()
            from src.music_player.queue import _strip
            was_empty = q.current_index < 0
            insert_at = q.current_index + 1 if q.current_index >= 0 else 0
            q.tracks.insert(insert_at, _strip(track))
            if was_empty:
                q.current_index = 0
            q._save()
            get_bridge().queue_changed.emit()
            if was_empty:
                get_bridge().play_track(track)
            return

        if action == "play_now_keep":
            # Insert at top of queue and play immediately without clearing the rest
            q = get_queue()
            from src.music_player.queue import _strip
            insert_at = q.current_index + 1 if q.current_index >= 0 else 0
            q.tracks.insert(insert_at, _strip(track))
            q.current_index = insert_at
            q._save()
            get_bridge().queue_changed.emit()
            get_bridge().play_track(track)
            self.highlight_track_id(track.get("id", ""))
            return

        # Default: play_now — replace queue and start playing
        playable = [
            t for i, t in enumerate(self._tracks)
            if i not in self._unmatched and t and not t.get("_missing")
        ]
        idx = playable.index(track) if track in playable else 0
        get_queue().set_queue(playable, start=idx)
        get_bridge().play_track(track)
        self.track_activated.emit(track)
        self.highlight_track_id(track["id"])

    def _on_context_menu(self, pos) -> None:
        row = self.rowAt(pos.y())
        if row < 0 or row >= len(self._raw):
            return

        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu{{background:#1a1a1e;color:#ddd;border:1px solid #2a2a2e;"
            f"font-family:{MDL2_FAMILY_CSS};}}"
            "QMenu::item{padding:6px 18px;}"
            "QMenu::item:selected{background:#2dd4bf;color:#000;}"
        )

        if row in self._unmatched:
            act = menu.addAction(f"{SEARCH}  Search for match…")
            if menu.exec(self.mapToGlobal(pos)) == act:
                self.search_requested.emit(row, self._raw[row])
            return

        if row < len(self._tracks) and (
            self._tracks[row].get("_missing") or
            self._tracks[row].get("id", "").startswith("ext-")
        ):
            t        = self._tracks[row]
            is_ext   = t.get("id", "").startswith("ext-")
            auto_lbl = f"{SEARCH}  Download and play" if is_ext else f"{SEARCH}  Auto-search"
            auto_act = menu.addAction(auto_lbl)
            find_act = menu.addAction(f"{SEARCH}  Search manually…")
            chosen   = menu.exec(self.mapToGlobal(pos))
            if chosen == auto_act:
                self._play_missing(t)
            elif chosen == find_act:
                self._open_resolve_dialog(t)
            return

        track    = self._tracks[row]
        play_now  = menu.addAction(f"{PLAY}  Play Now")
        play_next = menu.addAction(f"{NEXT}  Play Next")
        add_queue = menu.addAction(f"{ADD}  Add to Queue")
        menu.addSeparator()

        # "Add to Playlist" submenu — populated from all known server playlists
        import src.music_player.image_store as _img_store
        server_playlists = _img_store.get_playlists()
        pl_actions: dict = {}   # QAction → playlist dict
        if server_playlists and track.get("id"):
            pl_menu = QMenu("Add to Playlist", menu)
            pl_menu.setStyleSheet(
                f"QMenu{{background:#1a1a1e;color:#ddd;border:1px solid #2a2a2e;"
                f"font-family:{MDL2_FAMILY_CSS};}}"
                "QMenu::item{padding:6px 18px;}"
                "QMenu::item:selected{background:#2dd4bf;color:#000;}"
            )
            # Highlight the active (last-touched) playlist
            from src.music_player.ui.last_playlist import get_last
            last_pl = get_last()
            active_id = last_pl["pl_id"] if last_pl else ""
            for pl in server_playlists:
                label = pl.get("name", "")
                if pl.get("id") == active_id:
                    label = f"{label}  ✓"
                act = pl_menu.addAction(label)
                pl_actions[act] = pl
            menu.addMenu(pl_menu)

        pin_act = menu.addAction("Pin to sidebar")
        action  = menu.exec(self.mapToGlobal(pos))

        if action == play_now:
            playable = [
                t for i, t in enumerate(self._tracks)
                if i not in self._unmatched and t and not t.get("_missing")
            ]
            idx = playable.index(track) if track in playable else 0
            get_queue().set_queue(playable, start=idx)
            get_bridge().play_track(track)
            self.highlight_track_id(track["id"])
        elif action == play_next:
            q = get_queue()
            q.tracks.insert(q.current_index + 1, track)
            q._save()
        elif action == add_queue:
            get_queue().add_track(track)
        elif action in pl_actions:
            pl = pl_actions[action]
            self._add_to_playlist(track["id"], pl.get("id", ""), pl.get("name", ""))
        elif action == pin_act:
            from src.music_player.ui.pins import add_pin
            add_pin({
                "type": "track",
                "id": track.get("id", ""),
                "name": track.get("title", ""),
                "artist": track.get("artist", ""),
            })

    def _add_to_playlist(self, song_id: str, pl_id: str, pl_name: str) -> None:
        from src.music_player.ui.workers.image_loader import _launch

        class _W(QThread):
            def __init__(self, sid, pid):
                super().__init__()
                self._sid, self._pid = sid, pid
            def run(self):
                from src.music_player.repository.subsonic_client import SubsonicClient
                SubsonicClient().add_songs_to_playlist(self._pid, [self._sid])

        _launch(_W(song_id, pl_id))

    def _on_cell_clicked(self, row: int, col: int) -> None:
        if row in self._unmatched or row >= len(self._tracks):
            return
        track = self._tracks[row]
        if track.get("_missing"):
            return
        if col == _COL_ARTIST:
            artist = track.get("artist", "")
            if artist:
                nav_bus().show_artist.emit(artist)
        elif col == _COL_ALBUM:
            album_id   = track.get("albumId", "")
            album_name = track.get("album", "")
            artist     = track.get("artist", "")
            if album_name:
                nav_bus().show_album.emit(album_id, album_name, artist)

    def _on_mouse_move(self, event) -> None:
        idx = self.indexAt(event.pos())
        if idx.isValid() and idx.column() in (_COL_ARTIST, _COL_ALBUM):
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

    def _open_resolve_dialog(self, track: dict) -> None:
        """Open the search dialog pre-filled with the missing track's title+artist."""
        from src.music_player.ui.components.search_dialog import SearchResultsDialog
        query = f"{track.get('title', '')} {track.get('artist', '')}".strip()
        dlg   = SearchResultsDialog(initial_query=query, tracks_only=True, parent=self)
        dlg.setWindowTitle(f"Find: {track.get('title', '?')}")
        dlg.exec()

    def _play_missing(self, track: dict, attempt: int = 0) -> None:
        """Auto-search for a missing/ext-deezer track; retry while it downloads."""
        from PyQt6.QtCore import QTimer
        from src.music_player.ui.workers.download_worker import SearchAndPlayWorker
        from src.music_player.ui.workers.image_loader import _launch

        _MAX_ATTEMPTS = 18    # ~4.5 min at 15 s intervals
        _RETRY_MS     = 15_000

        def _on_found(match: dict) -> None:
            from PyQt6.QtCore import QTimer
            bridge = get_bridge()
            bridge.status_message.emit("")

            # Build the playable queue with the resolved track substituted in
            playable  = []
            start_idx = 0
            for i, t in enumerate(self._tracks):
                if t.get("_missing") or t.get("id", "").startswith("ext-"):
                    if t is track:
                        start_idx = len(playable)
                        playable.append(match)
                elif i not in self._unmatched and t:
                    playable.append(t)

            # Update the table row so the track shows as local (no longer grey)
            row_idx = next((i for i, t in enumerate(self._tracks) if t is track), None)
            if row_idx is not None:
                self._tracks[row_idx] = match
                self._style_row(row_idx)

            # Only start playback if the user hasn't moved on to something else
            current = bridge._current_track
            user_moved_on = (
                current is not None and
                current.get("id") != track.get("id") and
                not current.get("id", "").startswith("ext-") and
                bridge._controller.is_playing
            )
            if user_moved_on:
                bridge.status_message.emit("Download complete — click to play")
                QTimer.singleShot(4000, lambda: bridge.status_message.emit(""))
                return

            get_queue().set_queue(playable, start=start_idx)
            bridge.play_track(match)
            self.highlight_track_id(match["id"])

        def _on_downloading() -> None:
            if attempt >= _MAX_ATTEMPTS:
                get_bridge().status_message.emit("Download timed out")
                QTimer.singleShot(4000, lambda: get_bridge().status_message.emit(""))
                return
            next_attempt = attempt + 1
            get_bridge().status_message.emit(f"Downloading… ({next_attempt}/{_MAX_ATTEMPTS})")
            def _retry():
                try:
                    self._play_missing(track, next_attempt)
                except RuntimeError:
                    pass
            QTimer.singleShot(_RETRY_MS, _retry)

        def _on_not_found() -> None:
            get_bridge().status_message.emit("Not found — right-click to search manually")
            QTimer.singleShot(4000, lambda: get_bridge().status_message.emit(""))

        if attempt == 0:
            get_bridge().status_message.emit("Searching…")
        worker = SearchAndPlayWorker(track.get("title", ""), track.get("artist", ""))
        worker.found.connect(_on_found)
        worker.downloading.connect(_on_downloading)
        worker.not_found.connect(_on_not_found)
        _launch(worker)
