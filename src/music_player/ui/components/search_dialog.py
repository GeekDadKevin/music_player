"""Global search results dialog — Artists · Albums · Tracks."""

from typing import Callable

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

import src.music_player.image_store as image_store
from src.music_player.logging import get_logger
from src.music_player.ui.glyphs import MDL2_FAMILY_CSS, SEARCH
from src.music_player.ui.workers.search import SearchAllWorker

logger = get_logger(__name__)

_BG     = "#111114"
_BG_HOV = "#1a1a1e"


class _ResultRow(QWidget):
    """Single clickable row: 36×36 thumbnail + primary text + secondary text."""

    def __init__(self, primary: str, secondary: str,
                 pixmap: QPixmap | None, on_click: Callable, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._on_click = on_click
        self._apply_bg(False)

        h = QHBoxLayout(self)
        h.setContentsMargins(8, 4, 8, 4)
        h.setSpacing(10)

        thumb = QLabel()
        thumb.setFixedSize(36, 36)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if pixmap and not pixmap.isNull():
            thumb.setPixmap(
                pixmap.scaled(36, 36,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                ).copy(0, 0, 36, 36)
            )
            thumb.setStyleSheet("background:transparent; border-radius:4px;")
        else:
            thumb.setStyleSheet("background:#1e1e22; border-radius:4px;")
        h.addWidget(thumb)

        text = QVBoxLayout()
        text.setSpacing(1)
        text.setContentsMargins(0, 0, 0, 0)

        p = QLabel(primary)
        p.setStyleSheet("color:#ddd; font-size:13px; background:transparent;")
        p.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        text.addStretch()
        text.addWidget(p)

        if secondary:
            s = QLabel(secondary)
            s.setStyleSheet("color:#666; font-size:11px; background:transparent;")
            s.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            text.addWidget(s)

        text.addStretch()
        h.addLayout(text, stretch=1)

    def _apply_bg(self, hover: bool) -> None:
        self.setStyleSheet(
            f"background:{'#1a1a1e' if hover else 'transparent'}; border-radius:4px;"
        )

    def enterEvent(self, event) -> None:
        self._apply_bg(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._apply_bg(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_click()
        super().mousePressEvent(event)


class SearchResultsDialog(QDialog):
    def __init__(self, initial_query: str = "", tracks_only: bool = False,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Search Library")
        self.setMinimumSize(540, 460)
        self.setMaximumHeight(760)
        self.setStyleSheet(f"background:{_BG}; color:#ddd;")
        self._worker = None
        self._tracks_only = tracks_only
        self._build_ui()
        if initial_query:
            self._search_box.setText(initial_query)
            QTimer.singleShot(0, self._do_search)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # Search bar
        bar = QHBoxLayout()
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search artists, albums, tracks…")
        self._search_box.setStyleSheet(
            "QLineEdit{background:#1e1e22;color:#fff;border:1px solid #333;"
            "border-radius:6px;padding:6px 12px;font-size:13px;}"
            "QLineEdit:focus{border-color:#2dd4bf;}"
        )
        self._search_box.returnPressed.connect(self._do_search)
        bar.addWidget(self._search_box, stretch=1)

        go_btn = QPushButton(f"{SEARCH}  Search")
        go_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        go_btn.setStyleSheet(
            f"QPushButton{{background:#2dd4bf;color:#000;border:none;"
            f"border-radius:6px;padding:6px 14px;font-weight:700;font-size:13px;"
            f"font-family:{MDL2_FAMILY_CSS};}}"
            "QPushButton:hover{background:#38ebd5;}"
        )
        go_btn.clicked.connect(self._do_search)
        bar.addWidget(go_btn)
        root.addLayout(bar)

        self._status = QLabel("")
        self._status.setStyleSheet(
            "color:#666; font-size:12px; background:transparent;"
        )
        root.addWidget(self._status)

        # Results scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border:none; background:transparent;")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._results_widget = QWidget()
        self._results_widget.setStyleSheet("background:transparent;")
        self._results_layout = QVBoxLayout(self._results_widget)
        self._results_layout.setContentsMargins(0, 0, 0, 0)
        self._results_layout.setSpacing(0)
        self._results_layout.addStretch()

        scroll.setWidget(self._results_widget)
        root.addWidget(scroll, stretch=1)

    def _clear_results(self) -> None:
        while self._results_layout.count():
            item = self._results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _do_search(self) -> None:
        query = self._search_box.text().strip()
        if not query:
            return
        self._clear_results()
        self._status.setText("Searching…")
        if self._worker and self._worker.isRunning():
            self._worker.quit()
        self._worker = SearchAllWorker(query, parent=self)
        self._worker.results_ready.connect(self._on_results)
        self._worker.error.connect(lambda e: self._status.setText(f"Error: {e}"))
        self._worker.start()

    @pyqtSlot(dict)
    def _on_results(self, results: dict) -> None:
        self._clear_results()
        artists = results.get("artists", [])
        albums  = results.get("albums",  [])
        tracks  = results.get("tracks",  [])

        if self._tracks_only:
            artists = []
            albums  = []

        if not (artists or albums or tracks):
            self._status.setText("No results.")
            self._results_layout.addStretch()
            return

        n_a, n_al, n_t = len(artists), len(albums), len(tracks)
        if self._tracks_only:
            self._status.setText(f"{n_t} track{'s' if n_t != 1 else ''}")
        else:
            self._status.setText(
                f"{n_a} artist{'s' if n_a != 1 else ''}  ·  "
                f"{n_al} album{'s' if n_al != 1 else ''}  ·  "
                f"{n_t} track{'s' if n_t != 1 else ''}"
            )

        # ── Artists ──────────────────────────────────────────────────
        if artists:
            self._results_layout.addWidget(_section_label("Artists"))
            for a in artists:
                name  = a.get("name", "")
                count = a.get("albumCount", 0)
                sub   = f"{count} {'album' if count == 1 else 'albums'}" if count else ""
                px    = _artist_pixmap(name)

                def _click(n=name):
                    from src.music_player.ui.navigation import nav_bus
                    nav_bus().show_artist.emit(n)
                    self.accept()

                self._results_layout.addWidget(
                    _ResultRow(name, sub, px, _click, parent=self._results_widget)
                )
            self._results_layout.addWidget(_divider())

        # ── Albums ───────────────────────────────────────────────────
        if albums:
            self._results_layout.addWidget(_section_label("Albums"))
            for al in albums:
                name   = al.get("name", "")
                artist = al.get("artist", "")
                al_id  = al.get("id", "")
                px     = _cover_pixmap(al.get("coverArt", ""))

                def _click(aid=al_id, n=name, ar=artist):
                    from src.music_player.ui.navigation import nav_bus
                    nav_bus().show_album.emit(aid, n, ar)
                    self.accept()

                self._results_layout.addWidget(
                    _ResultRow(name, artist, px, _click, parent=self._results_widget)
                )
            self._results_layout.addWidget(_divider())

        # ── Tracks ───────────────────────────────────────────────────
        if tracks:
            self._results_layout.addWidget(_section_label("Tracks"))
            for t in tracks:
                title  = t.get("title", "")
                artist = t.get("artist", "")
                album  = t.get("album", "")
                sub    = f"{artist}  ·  {album}" if album else artist
                px     = _cover_pixmap(t.get("coverArt", ""))

                def _click(track=t):
                    from src.music_player.ui.components.playback_bridge import get_bridge
                    get_bridge().play_track(track)
                    self.accept()

                self._results_layout.addWidget(
                    _ResultRow(title, sub, px, _click, parent=self._results_widget)
                )

        self._results_layout.addStretch()


# ── helpers ───────────────────────────────────────────────────────────

def _artist_pixmap(name: str) -> QPixmap | None:
    return _cover_pixmap_from_key(f"artist:{name.lower()}")


def _cover_pixmap(cover_art_id: str) -> QPixmap | None:
    return _cover_pixmap_from_key(f"album:{cover_art_id}") if cover_art_id else None


def _cover_pixmap_from_key(key: str) -> QPixmap | None:
    data = image_store.get(key)
    if not data:
        return None
    px = QPixmap()
    return px if px.loadFromData(data) and not px.isNull() else None


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        "color:#666; font-size:11px; font-weight:700; letter-spacing:0.06em;"
        "padding:10px 8px 4px 8px; background:transparent;"
    )
    return lbl


def _divider() -> QWidget:
    w = QWidget()
    w.setFixedHeight(1)
    w.setStyleSheet("background:#222226; margin:4px 0;")
    return w
