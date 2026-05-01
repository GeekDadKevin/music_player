from pathlib import Path

from PyQt6.QtCore import Qt, QSettings, pyqtSlot
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QHBoxLayout, QMainWindow,
    QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

_SETTINGS_FILE = Path.home() / ".music-player" / "window_state.ini"

from src.music_player.logging import get_logger
from src.music_player.ui.components.library_page import LibraryPage
from src.music_player.ui.components.player_bar import PlayerBar
from src.music_player.ui.components.playlist_page import PlaylistPage
from src.music_player.ui.components.queue_panel import QueuePanel
from src.music_player.ui.components.visualizer_panel import VisualizerPanel
from src.music_player.ui.glyphs import MDL2_FONT
from src.music_player.ui.sidebar_widget import SidebarWidget

logger = get_logger(__name__)

# Page indices in the QStackedWidget
_IDX_BROWSE    = 0
_IDX_QUEUE     = 1
_IDX_PLAYLISTS = 2   # navigated to via sidebar playlist click, not a nav button


class MusicPlayerWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Music Player")
        self.setMinimumSize(1200, 800)
        self._init_ui()

    def _init_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        # ── sidebar ──────────────────────────────────────────────────
        self._sidebar = SidebarWidget()
        self._sidebar.nav_changed.connect(self._on_nav)
        self._sidebar.playlist_clicked.connect(self._on_sidebar_playlist)
        self._sidebar.pin_item_clicked.connect(self._on_pin_clicked)
        self._sidebar.playlist_play.connect(
            lambda pid, n: self._playlist_page.play_playlist(pid, n, "play")
        )
        self._sidebar.playlist_shuffle.connect(
            lambda pid, n: self._playlist_page.play_playlist(pid, n, "shuffle")
        )
        self._sidebar.playlist_append.connect(
            lambda pid, n: self._playlist_page.play_playlist(pid, n, "append")
        )

        # ── page stack ───────────────────────────────────────────────
        self._stack = QStackedWidget()
        self._browse_page = LibraryPage()
        self._stack.addWidget(self._browse_page)          # 0 Browse
        self._browse_page.playlist_selected.connect(self._on_sidebar_playlist)
        from src.music_player.ui.components.library_page import QueueTab
        self._queue_page = QueueTab()
        self._stack.addWidget(self._queue_page)           # 1 Queue
        self._playlist_page = PlaylistPage()
        self._playlist_page.playlist_imported.connect(self._sidebar.add_imported_playlist)
        self._playlist_page.playlist_renamed.connect(
            lambda old, new, src, pid: self._sidebar.rename_playlist(old, new, src, pid)
        )
        self._playlist_page.playlist_deleted.connect(
            lambda name, src: self._sidebar.remove_playlist(name, src)
        )
        self._playlist_page.playlist_created.connect(self._sidebar.add_server_playlist)
        self._playlist_page.playlist_activated.connect(self._sidebar.set_active_playlist)
        self._stack.addWidget(self._playlist_page)        # 2 Playlists

        # ── queue panel (hidden by default) ──────────────────────────
        self._queue_panel = QueuePanel()
        self._queue_panel.setVisible(False)

        # ── main area — splitter so sidebar is user-resizable ─────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(2)
        splitter.setStyleSheet(
            "QSplitter::handle { background: #1e1e22; }"
            "QSplitter::handle:hover { background: #2dd4bf; }"
        )
        splitter.addWidget(self._sidebar)
        splitter.addWidget(self._stack)
        splitter.addWidget(self._queue_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([280, 920, 0])
        self._splitter = splitter
        root.addWidget(splitter, stretch=1)

        # ── visualizer panel (hidden by default) ─────────────────────
        self._viz_panel = VisualizerPanel()
        self._viz_panel.setVisible(False)
        self._viz_panel.fullscreen_requested.connect(self._toggle_viz_fullscreen)
        root.addWidget(self._viz_panel)

        # ── player bar ───────────────────────────────────────────────
        self._player_bar = PlayerBar()
        self._player_bar.setFixedHeight(80)
        self._player_bar.queue_toggled.connect(self._toggle_queue)
        self._player_bar.visualizer_toggled.connect(self._toggle_visualizer)
        root.addWidget(self._player_bar)

        self._root_layout  = root
        self._viz_fullscreen = False
        self._stack.setCurrentIndex(_IDX_BROWSE)
        self._restore_state()
        self._setup_media_shortcuts()

    # ── window state persistence ──────────────────────────────────────

    def closeEvent(self, event) -> None:
        self._save_state()
        super().closeEvent(event)

    def _save_state(self) -> None:
        _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        s = QSettings(str(_SETTINGS_FILE), QSettings.Format.IniFormat)
        s.setValue("window/geometry", self.saveGeometry())
        s.setValue("window/splitter", self._splitter.sizes())

    def _restore_state(self) -> None:
        s = QSettings(str(_SETTINGS_FILE), QSettings.Format.IniFormat)
        geom = s.value("window/geometry")
        if geom:
            self.restoreGeometry(geom)
        sizes = s.value("window/splitter")
        if sizes:
            try:
                self._splitter.setSizes([int(x) for x in sizes])
            except (TypeError, ValueError):
                pass

    # ── slot handlers ─────────────────────────────────────────────────

    @pyqtSlot(str)
    def _on_nav(self, name: str) -> None:
        idx = {"Browse": _IDX_BROWSE, "Queue": _IDX_QUEUE}.get(name, 0)
        if name == "Queue":
            self._queue_page.refresh()
        self._stack.setCurrentIndex(idx)

    @pyqtSlot(str, str)
    def _on_sidebar_playlist(self, pl_id: str, name: str) -> None:
        """Route to the correct playlist show method based on id prefix."""
        self._stack.setCurrentIndex(_IDX_PLAYLISTS)
        if pl_id.startswith("__import__"):
            self._playlist_page.show_imported_playlist(name)
        else:
            self._playlist_page.show_server_playlist(pl_id, name)

    @pyqtSlot(dict)
    def _on_pin_clicked(self, pin: dict) -> None:
        kind = pin.get("type")
        if kind == "playlist":
            self._on_sidebar_playlist(pin.get("id", ""), pin.get("name", ""))
        elif kind == "artist":
            self._stack.setCurrentIndex(_IDX_BROWSE)
            self._sidebar.set_active_nav("Browse")
            self._browse_page._show_artist(pin)
        elif kind in ("album", "track"):
            # Play the track immediately; album nav wired later
            if kind == "track":
                from src.music_player.ui.components.playback_bridge import get_bridge
                get_bridge().play_track(pin)

    def _toggle_queue(self) -> None:
        visible = not self._queue_panel.isVisible()
        self._queue_panel.setVisible(visible)
        if visible:
            self._queue_panel.refresh()
            sizes = self._splitter.sizes()
            if sizes[2] < 10:          # panel was collapsed — open it
                total = sum(sizes)
                self._splitter.setSizes([sizes[0], total - sizes[0] - 280, 280])
        else:
            sizes = self._splitter.sizes()
            self._splitter.setSizes([sizes[0], sizes[1] + sizes[2], 0])

    def _toggle_visualizer(self) -> None:
        if self._viz_fullscreen:
            self._exit_viz_fullscreen()
        else:
            self._viz_panel.setVisible(not self._viz_panel.isVisible())

    def _toggle_viz_fullscreen(self) -> None:
        if self._viz_fullscreen:
            self._exit_viz_fullscreen()
        else:
            self._enter_viz_fullscreen()

    def _enter_viz_fullscreen(self) -> None:
        if not self._viz_panel.isVisible():
            self._viz_panel.setVisible(True)
        self._splitter.hide()
        self._player_bar.hide()
        # Give the visualizer panel all the stretch so it fills the window.
        self._root_layout.setStretch(self._root_layout.indexOf(self._splitter),  0)
        self._root_layout.setStretch(self._root_layout.indexOf(self._viz_panel), 1)
        self._root_layout.setStretch(self._root_layout.indexOf(self._player_bar), 0)
        self._viz_panel.set_fullscreen_active(True)
        self._viz_fullscreen = True
        self.showFullScreen()

    def _exit_viz_fullscreen(self) -> None:
        self.showNormal()
        self._splitter.show()
        self._player_bar.show()
        self._root_layout.setStretch(self._root_layout.indexOf(self._splitter),  1)
        self._root_layout.setStretch(self._root_layout.indexOf(self._viz_panel), 0)
        self._root_layout.setStretch(self._root_layout.indexOf(self._player_bar), 0)
        self._viz_panel.set_fullscreen_active(False)
        self._viz_fullscreen = False

    def _setup_media_shortcuts(self) -> None:
        from src.music_player.ui.components.playback_bridge import get_bridge
        bridge = get_bridge()
        for key in (Qt.Key.Key_MediaPlay, Qt.Key.Key_MediaTogglePlayPause):
            QShortcut(QKeySequence(key), self).activated.connect(bridge.play_pause)
        QShortcut(QKeySequence(Qt.Key.Key_MediaNext), self).activated.connect(bridge.next_track)
        QShortcut(QKeySequence(Qt.Key.Key_MediaPrevious), self).activated.connect(bridge.previous_track)
        QShortcut(QKeySequence(Qt.Key.Key_MediaStop), self).activated.connect(bridge.stop)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self._viz_fullscreen:
            self._exit_viz_fullscreen()
        else:
            super().keyPressEvent(event)


