from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QHBoxLayout, QMainWindow,
    QPushButton, QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

from src.music_player.logging import get_logger
from src.music_player.ui.components.library_page import LibraryPage
from src.music_player.ui.components.player_bar import PlayerBar
from src.music_player.ui.components.playlist_page import PlaylistPage
from src.music_player.ui.components.queue_panel import QueuePanel
from src.music_player.ui.glyphs import MDL2_FONT, SETTINGS
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

        # ── top bar — settings gear only ──────────────────────────────
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 6, 12, 6)
        top_bar.addStretch()

        gear_btn = QPushButton(SETTINGS)
        gear_btn.setFont(QFont(MDL2_FONT, 14))
        gear_btn.setFixedSize(36, 36)
        gear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        gear_btn.setToolTip("Settings")
        gear_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#666;border:none;"
            "border-radius:18px;}"
            "QPushButton:hover{color:#fff;background:#1e1e22;}"
        )
        gear_btn.clicked.connect(self._open_settings)
        top_bar.addWidget(gear_btn)
        root.addLayout(top_bar)

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

        # ── player bar ───────────────────────────────────────────────
        self._player_bar = PlayerBar()
        self._player_bar.setFixedHeight(80)
        self._player_bar.queue_toggled.connect(self._toggle_queue)
        root.addWidget(self._player_bar)

        self._stack.setCurrentIndex(_IDX_BROWSE)

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

    def _open_settings(self) -> None:
        from src.music_player.ui.components.settings_dialog import SettingsDialog
        SettingsDialog(parent=self).exec()


